from __future__ import annotations

import html
import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any, Callable, TypeVar
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from .config import Settings, get_settings
from .db import database_ready, transaction
from .logging_json import configure_logging
from .repository import (
    ConflictError,
    NotFoundError,
    add_change_order,
    add_completion,
    begin_idempotency,
    complete_idempotency,
    enqueue,
    finish_webhook,
    get_document,
    get_document_by_envelope,
    get_job,
    get_job_by_square_invoice,
    log_portal_access,
    portal_payload,
    record_webhook,
    requeue_dead_event,
    reset_document_for_retry,
    rotate_portal_token_version,
    save_ai_report_notice,
    total_paid_cents,
    transition_job,
    ar_aging_summary,
    create_collection_hold,
    create_staff_alert,
    ensure_message_thread,
    find_message_thread_by_phone,
    get_ar_case,
    get_ar_case_by_job,
    get_message_thread,
    get_sms_consent,
    list_ar_cases,
    list_open_ar_cases_by_phone,
    list_staff_alerts,
    list_thread_messages,
    record_message_event,
    release_collection_holds,
    update_ar_case,
    update_message_delivery,
    update_message_thread,
    update_staff_alert,
    upsert_sms_consent,
    update_document,
    upsert_job,
)
from .schemas import (
    AiReportInput, ArHoldRequest, ArResumeRequest, ChangeOrderRequest, CompletionRequest,
    ManualReplyRequest, SmsConsentRequest, StaffAlertUpdateRequest, StartWorkRequest, SyncEstimateRequest,
)
from .security import (
    AuthenticationError,
    create_portal_token,
    decode_portal_token,
    privacy_hash,
    sha256_hex,
    verify_internal_request,
    verify_shared_secret,
    verify_square_webhook,
    verify_twilio_webhook,
)
from .message_policy import keyword_decision
from .phone import normalize_e164
from .state_machine import InvalidTransition, StartWorkDecision, WorkflowState, start_work_decision

class LabForceReminderRequest(BaseModel):
    age_days: int = Field(default=2, ge=0, le=365)


settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)
app = FastAPI(title="Floodman Business API", version="3.0.0", docs_url=None if settings.production else "/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.roomflow_allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=[
        "content-type",
        "x-floodman-key-id",
        "x-floodman-timestamp",
        "x-floodman-signature",
        "idempotency-key",
    ],
)


@app.middleware("http")
async def body_limit_and_headers(request: Request, call_next: Callable[..., Any]) -> Response:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_size = int(content_length)
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        if declared_size < 0:
            return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        if declared_size > settings.webhook_max_body_bytes:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    return response


async def _verify_hmac(request: Request, keyring: dict[str, bytes]) -> str:
    body = await request.body()
    if len(body) > settings.webhook_max_body_bytes:
        raise HTTPException(status_code=413, detail="Request body too large")
    try:
        return verify_internal_request(
            request.headers,
            body,
            keyring,
            settings.internal_hmac_max_age_seconds,
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


async def internal_auth(request: Request) -> str:
    return await _verify_hmac(request, settings.internal_hmac_keys)


async def ai_auth(request: Request) -> str:
    return await _verify_hmac(request, settings.ai_hmac_keys)


T = TypeVar("T", bound=BaseModel)


def _canonical_hash(model: BaseModel) -> str:
    body = json.dumps(model.model_dump(mode="json"), separators=(",", ":"), sort_keys=True).encode()
    return sha256_hex(body)


def _idempotent(scope: str, model: T, action: Callable[[Any], dict[str, Any]]) -> dict[str, Any]:
    key = str(getattr(model, "idempotency_key"))
    with transaction() as conn:
        cached = begin_idempotency(conn, scope, key, _canonical_hash(model))
        if cached is not None:
            return dict(cached)
        result = action(conn)
        complete_idempotency(conn, scope, key, result)
        return result


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.exception_handler(InvalidTransition)
async def invalid_transition_handler(request: Request, exc: InvalidTransition) -> JSONResponse:
    # Workflow timing/state conflicts are actionable client conflicts, not server faults.
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok", "service": "floodman-orchestrator"}


@app.get("/health/ready")
def health_ready() -> JSONResponse:
    document_path_ok = settings.documents_path.exists() and settings.documents_path.is_dir()
    ready = database_ready() and document_path_ok
    return JSONResponse(
        {"status": "ready" if ready else "not_ready", "database": database_ready(), "document_path": document_path_ok},
        status_code=200 if ready else 503,
    )


@app.post("/internal/v1/jobs/sync-estimate")
def sync_estimate(request: SyncEstimateRequest, actor: str = Depends(internal_auth)) -> dict[str, Any]:
    def action(conn: Any) -> dict[str, Any]:
        job = upsert_job(conn, request)
        token = create_portal_token(
            str(job["id"]), int(job["portal_token_version"]), settings.portal_token_secret, settings.portal_token_ttl_seconds
        )
        return {
            "job_id": str(job["id"]),
            "state": job["state"],
            "revision": job["revision"],
            "portal_url": f"{settings.portal_base_url}/{token}",
        }

    return _idempotent("sync-estimate", request, action)


@app.get("/internal/v1/jobs/{job_id}")
def read_job(job_id: str, actor: str = Depends(internal_auth)) -> dict[str, Any]:
    with transaction() as conn:
        payload = portal_payload(conn, job_id)
        job = get_job(conn, job_id)
        payload["last_error"] = job.get("last_error")
        payload["provider_ids"] = {
            "gauzy_contact_id": job.get("gauzy_contact_id"),
            "gauzy_estimate_id": job.get("gauzy_estimate_id"),
            "gauzy_invoice_id": job.get("gauzy_invoice_id"),
            "gauzy_project_id": job.get("gauzy_project_id"),
            "square_invoice_id": job.get("square_invoice_id"),
            "square_final_invoice_id": job.get("square_final_invoice_id"),
        }
        return payload


@app.post("/internal/v1/jobs/{job_id}/portal-link")
def rotate_portal_link(
    job_id: str, request: StartWorkRequest, actor: str = Depends(internal_auth)
) -> dict[str, Any]:
    def action(conn: Any) -> dict[str, Any]:
        job = rotate_portal_token_version(conn, job_id)
        token = create_portal_token(
            job_id, int(job["portal_token_version"]), settings.portal_token_secret, settings.portal_token_ttl_seconds
        )
        return {"job_id": job_id, "portal_url": f"{settings.portal_base_url}/{token}"}

    return _idempotent(f"portal-link:{job_id}", request, action)


def _wait_for_start_reconciliation(
    job_id: str,
    *,
    timeout_seconds: float = 15.0,
    poll_seconds: float = 0.5,
) -> tuple[dict[str, Any], StartWorkDecision]:
    """Wait briefly for the asynchronous Square payment ledger to settle.

    This preflight runs before the idempotency transaction. Expected payment
    timing conflicts therefore do not reserve an idempotency key or surface as
    an HTTP 500. Each polling transaction is short-lived so the outbox worker
    remains free to write the reconciled payment and workflow state.
    """

    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        with transaction() as conn:
            job = get_job(conn, job_id)
            decision = start_work_decision(
                job["state"],
                deposit_cents=int(job["deposit_cents"]),
                recorded_paid_cents=total_paid_cents(conn, job_id),
            )
        if decision != StartWorkDecision.PAYMENT_PENDING or time.monotonic() >= deadline:
            return job, decision
        time.sleep(max(0.05, poll_seconds))


@app.post("/internal/v1/jobs/{job_id}/start")
def start_work(job_id: str, request: StartWorkRequest, actor: str = Depends(internal_auth)) -> dict[str, Any]:
    preflight_job, preflight_decision = _wait_for_start_reconciliation(job_id)
    if preflight_decision == StartWorkDecision.PAYMENT_PENDING:
        raise ConflictError(
            "The deposit payment is still being verified. Wait a few seconds, refresh the job, "
            "and press Start work again."
        )
    if preflight_decision == StartWorkDecision.BLOCKED:
        raise ConflictError(
            f"Work cannot start while the job is {preflight_job['state']}. "
            "The Work Authorization must be signed and the required deposit must be verified first."
        )
    if preflight_decision == StartWorkDecision.ALREADY_STARTED:
        return {
            "job_id": job_id,
            "state": preflight_job["state"],
            "already_started": True,
        }

    def action(conn: Any) -> dict[str, Any]:
        job = get_job(conn, job_id, for_update=True)
        recorded_paid = total_paid_cents(conn, job_id)
        decision = start_work_decision(
            job["state"],
            deposit_cents=int(job["deposit_cents"]),
            recorded_paid_cents=recorded_paid,
        )

        if decision == StartWorkDecision.ALREADY_STARTED:
            return {
                "job_id": job_id,
                "state": job["state"],
                "already_started": True,
            }

        if decision == StartWorkDecision.PAYMENT_PENDING:
            raise ConflictError(
                "The deposit payment is still being verified. Wait a few seconds, refresh the job, "
                "and press Start work again."
            )

        if decision == StartWorkDecision.BLOCKED:
            raise ConflictError(
                f"Work cannot start while the job is {job['state']}. "
                "The Work Authorization must be signed and the required deposit must be verified first."
            )

        repaired = False
        if decision == StartWorkDecision.REPAIR_DEPOSIT_STATE_AND_READY:
            transition_job(conn, job_id, WorkflowState.DEPOSIT_PAID)
            repaired = True

        result = transition_job(conn, job_id, WorkflowState.IN_PROGRESS)
        return {
            "job_id": job_id,
            "state": result["state"],
            "deposit_state_repaired": repaired,
        }

    return _idempotent(f"start:{job_id}", request, action)


@app.post("/internal/v1/jobs/{job_id}/change-orders")
def create_change_order(
    job_id: str, request: ChangeOrderRequest, actor: str = Depends(internal_auth)
) -> dict[str, Any]:
    def action(conn: Any) -> dict[str, Any]:
        document = add_change_order(conn, job_id, request)
        return {"job_id": job_id, "document_id": str(document["id"]), "status": document["status"]}

    return _idempotent(f"change-order:{job_id}", request, action)


@app.post("/internal/v1/jobs/{job_id}/completion")
def create_completion(
    job_id: str, request: CompletionRequest, actor: str = Depends(internal_auth)
) -> dict[str, Any]:
    def action(conn: Any) -> dict[str, Any]:
        document = add_completion(conn, job_id, request)
        return {"job_id": job_id, "document_id": str(document["id"]), "status": document["status"]}

    return _idempotent(f"completion:{job_id}", request, action)


@app.post("/internal/v1/documents/{document_id}/retry")
def retry_document(
    document_id: str, request: StartWorkRequest, actor: str = Depends(internal_auth)
) -> dict[str, Any]:
    def action(conn: Any) -> dict[str, Any]:
        document = reset_document_for_retry(conn, document_id)
        return {"document_id": document_id, "status": document["status"]}

    return _idempotent(f"document-retry:{document_id}", request, action)


@app.post("/internal/v1/outbox/{event_id}/retry")
def retry_dead_event(
    event_id: str, request: StartWorkRequest, actor: str = Depends(internal_auth)
) -> dict[str, Any]:
    def action(conn: Any) -> dict[str, Any]:
        event = requeue_dead_event(conn, event_id)
        return {"event_id": event_id, "status": event["status"], "event_type": event["event_type"]}

    return _idempotent(f"outbox-retry:{event_id}", request, action)


@app.post("/internal/v1/ai/reports")
def ai_report(report: AiReportInput, actor: str = Depends(ai_auth)) -> dict[str, bool]:
    with transaction() as conn:
        save_ai_report_notice(conn, report.model_dump(mode="json"))
    return {"accepted": True}


def _square_invoice_id(payload: dict[str, Any]) -> str | None:
    obj = ((payload.get("data") or {}).get("object") or {})
    for candidate in (obj.get("invoice"), obj.get("payment"), obj.get("refund"), obj):
        if not isinstance(candidate, dict):
            continue
        invoice_id = candidate.get("invoice_id")
        if invoice_id:
            return str(invoice_id)
        if candidate is obj.get("invoice") and candidate.get("id"):
            return str(candidate["id"])
    return None


@app.post("/webhooks/square")
async def square_webhook(request: Request, x_square_hmacsha256_signature: str = Header(default="")) -> dict[str, bool]:
    body = await request.body()
    if len(body) > settings.webhook_max_body_bytes:
        raise HTTPException(status_code=413, detail="Request body too large")
    if not verify_square_webhook(
        settings.square_webhook_signature_key,
        settings.square_webhook_notification_url,
        body,
        x_square_hmacsha256_signature,
    ):
        raise HTTPException(status_code=401, detail="Invalid Square signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    event_id = str(payload.get("event_id") or payload.get("eventId") or sha256_hex(body))
    event_type = str(payload.get("type") or "unknown")
    with transaction() as conn:
        if not record_webhook(conn, "square", event_id, event_type, body):
            return {"accepted": True}
        invoice_id = _square_invoice_id(payload)
        if not invoice_id:
            finish_webhook(conn, "square", event_id, "IGNORED", "No invoice id in event")
            return {"accepted": True}
        job = get_job_by_square_invoice(conn, invoice_id)
        if not job:
            finish_webhook(conn, "square", event_id, "IGNORED", "Invoice is not mapped")
            return {"accepted": True}
        enqueue(
            conn,
            str(job["id"]),
            "PROCESS_SQUARE_EVENT",
            {"invoice_id": invoice_id, "provider_event_id": event_id, "event_type": event_type},
        )
        finish_webhook(conn, "square", event_id, "PROCESSED")
    return {"accepted": True}




def _twilio_params(body: bytes) -> dict[str, object]:
    try:
        decoded = body.decode("utf-8")
        parsed = parse_qs(decoded, keep_blank_values=True, strict_parsing=False, max_num_fields=100)
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Malformed Twilio form body") from exc
    return {key: values[0] if len(values) == 1 else values for key, values in parsed.items()}


def _twilio_status(value: str) -> str:
    normalized = value.strip().lower()
    return {
        "queued": "SENT", "accepted": "SENT", "sending": "SENT", "sent": "SENT",
        "delivered": "DELIVERED", "undelivered": "UNDELIVERED", "failed": "FAILED",
        "received": "RECEIVED",
    }.get(normalized, "SENT")


@app.post("/webhooks/twilio/inbound", response_class=PlainTextResponse)
async def twilio_inbound(request: Request, x_twilio_signature: str = Header(default="")) -> PlainTextResponse:
    if not settings.twilio_enabled:
        raise HTTPException(status_code=404, detail="Twilio messaging is disabled")
    raw = await request.body()
    if len(raw) > settings.webhook_max_body_bytes:
        raise HTTPException(status_code=413, detail="Request body too large")
    params = _twilio_params(raw)
    if not verify_twilio_webhook(
        settings.twilio_auth_token,
        settings.twilio_inbound_webhook_url,
        params,
        x_twilio_signature,
    ):
        raise HTTPException(status_code=401, detail="Invalid Twilio signature")
    message_sid = str(params.get("MessageSid") or params.get("SmsMessageSid") or "")
    from_phone = normalize_e164(str(params.get("From") or ""))
    to_phone = normalize_e164(str(params.get("To") or ""))
    body_text = str(params.get("Body") or "")[:5000]
    if not message_sid or not from_phone:
        raise HTTPException(status_code=400, detail="Twilio message is missing MessageSid or From")
    opt_out_type = str(params.get("OptOutType") or "") or None
    keyword = keyword_decision(body_text, opt_out_type)
    with transaction() as conn:
        if not record_webhook(conn, "twilio", message_sid, "INBOUND_SMS", raw):
            return PlainTextResponse("<Response></Response>", media_type="application/xml")
        thread = find_message_thread_by_phone(conn, from_phone)
        open_cases = list_open_ar_cases_by_phone(conn, from_phone)
        if not thread and open_cases:
            seed_case = open_cases[0]
            seed_job = get_job(conn, str(seed_case["job_id"]))
            thread = ensure_message_thread(
                conn,
                organization_id=str(seed_case["organization_id"]),
                job_id=str(seed_job["id"]),
                ar_case_id=str(seed_case["id"]),
                customer_phone_e164=from_phone,
                customer_email=str(seed_case.get("recipient_email") or "") or None,
                business_phone_e164=to_phone or None,
            )
        if not thread or not open_cases:
            finish_webhook(conn, "twilio", message_sid, "IGNORED", "Phone is not linked to an active Floodman A/R case")
            return PlainTextResponse("<Response></Response>", media_type="application/xml")

        exact_matches = [
            item for item in open_cases
            if re.search(rf"(?<![A-Z0-9]){re.escape(str(item['invoice_number']).upper())}(?![A-Z0-9])", body_text.upper())
        ]
        multiple_open_case_ids: list[str] = []
        if len(open_cases) == 1:
            case = open_cases[0]
        elif len(exact_matches) == 1:
            case = exact_matches[0]
        else:
            linked_id = str(thread.get("ar_case_id") or "")
            case = next((item for item in open_cases if str(item["id"]) == linked_id), open_cases[0])
            if not keyword:
                multiple_open_case_ids = [str(item["id"]) for item in open_cases]
            for open_case in (open_cases if multiple_open_case_ids else []):
                create_collection_hold(
                    conn,
                    case=open_case,
                    hold_type="MANUAL",
                    reason="Inbound SMS could refer to more than one open Floodman invoice for this phone number.",
                    created_by="TWILIO_AMBIGUOUS_ACCOUNT_ROUTER",
                    metadata={"message_sid": message_sid, "open_case_ids": multiple_open_case_ids},
                )
            update_message_thread(conn, str(thread["id"]), status="HUMAN_REQUIRED")

        job = get_job(conn, str(case["job_id"]))
        if str(thread.get("job_id") or "") != str(job["id"]) or str(thread.get("ar_case_id") or "") != str(case["id"]):
            thread = update_message_thread(
                conn,
                str(thread["id"]),
                job_id=str(job["id"]),
                ar_case_id=str(case["id"]),
            )
        inbound = record_message_event(
            conn,
            thread_id=str(thread["id"]),
            job_id=str(job["id"]),
            ar_case_id=str(case["id"]),
            direction="INBOUND",
            channel="SMS",
            provider="twilio",
            provider_message_id=message_sid,
            message_kind="CUSTOMER_REPLY",
            body=body_text,
            status="RECEIVED",
            metadata={
                "from": from_phone,
                "to": to_phone,
                "num_media": str(params.get("NumMedia") or "0"),
                "opt_out_type": opt_out_type,
                "multiple_open_case_ids": multiple_open_case_ids,
            },
        )
        update_ar_case(conn, str(case["id"]), last_customer_message_at=datetime.now(UTC))
        decision = keyword
        if decision and decision.kind in {"STOP", "START"}:
            consent_status = "OPTED_OUT" if decision.kind == "STOP" else "OPTED_IN"
            consent_source = "TWILIO_STOP" if decision.kind == "STOP" else "TWILIO_START"
            audit_action = "SMS_OPTED_OUT" if decision.kind == "STOP" else "SMS_OPTED_IN"
            seen: set[tuple[str, str]] = set()
            for open_case in open_cases:
                open_job = get_job(conn, str(open_case["job_id"]))
                identity = (str(open_job["organization_id"]), str(open_job["id"]))
                if identity in seen:
                    continue
                seen.add(identity)
                upsert_sms_consent(
                    conn,
                    organization_id=identity[0],
                    job_id=identity[1],
                    phone_e164=from_phone,
                    status=consent_status,
                    source=consent_source,
                    captured_at=datetime.now(UTC),
                    evidence={"message_sid": message_sid, "keyword": decision.normalized_body},
                )
                audit(conn, identity[0], "CUSTOMER", from_phone, audit_action, "workflow_job", identity[1], {})
        elif decision and decision.kind == "HELP":
            enqueue(conn, str(job["id"]), "SEND_HELP_REPLY", {"message_id": str(inbound["id"])})
        else:
            enqueue(
                conn,
                str(job["id"]),
                "PROCESS_INBOUND_MESSAGE",
                {"message_id": str(inbound["id"]), "multiple_open_case_ids": multiple_open_case_ids},
            )
        finish_webhook(conn, "twilio", message_sid, "PROCESSED")
    # With Advanced Opt-Out enabled, Twilio handles its configured STOP/START acknowledgement.
    return PlainTextResponse("<Response></Response>", media_type="application/xml")


@app.post("/webhooks/twilio/status", response_class=PlainTextResponse)
async def twilio_status(request: Request, x_twilio_signature: str = Header(default="")) -> PlainTextResponse:
    if not settings.twilio_enabled:
        raise HTTPException(status_code=404, detail="Twilio messaging is disabled")
    raw = await request.body()
    if len(raw) > settings.webhook_max_body_bytes:
        raise HTTPException(status_code=413, detail="Request body too large")
    params = _twilio_params(raw)
    if not verify_twilio_webhook(
        settings.twilio_auth_token,
        settings.twilio_status_webhook_url,
        params,
        x_twilio_signature,
    ):
        raise HTTPException(status_code=401, detail="Invalid Twilio signature")
    message_sid = str(params.get("MessageSid") or "")
    provider_status = str(params.get("MessageStatus") or params.get("SmsStatus") or "")
    if not message_sid:
        raise HTTPException(status_code=400, detail="Twilio status is missing MessageSid")
    event_id = f"{message_sid}:{provider_status}:{sha256_hex(raw)[:16]}"
    with transaction() as conn:
        if not record_webhook(conn, "twilio", event_id, "MESSAGE_STATUS", raw):
            return PlainTextResponse("", status_code=204)
        event = update_message_delivery(
            conn,
            provider="twilio",
            provider_message_id=message_sid,
            status=_twilio_status(provider_status),
            error_code=str(params.get("ErrorCode") or "") or None,
            error_message=str(params.get("ErrorMessage") or "") or None,
            metadata={"twilio_status": provider_status},
        )
        if event and _twilio_status(provider_status) in {"FAILED", "UNDELIVERED"} and event.get("job_id"):
            job = get_job(conn, str(event["job_id"]))
            case_id = str(event.get("ar_case_id") or "") or None
            alert = create_staff_alert(
                conn,
                organization_id=str(job["organization_id"]),
                job_id=str(job["id"]),
                ar_case_id=case_id,
                thread_id=str(event["thread_id"]),
                alert_type="SMS_DELIVERY_FAILED",
                severity="WARNING",
                title=f"Customer text could not be delivered for invoice F-{job['invoice_number']}-FINAL",
                body=f"Twilio status: {provider_status}. Error: {params.get('ErrorCode') or 'not supplied'}.",
                metadata={"message_sid": message_sid, "provider_status": provider_status},
            )
            enqueue(conn, str(job["id"]), "SEND_STAFF_ALERT", {"alert_id": str(alert["id"])})
        finish_webhook(conn, "twilio", event_id, "PROCESSED")
    return PlainTextResponse("", status_code=204)


@app.post("/internal/v1/lab/force-reminders")
def force_lab_reminders(
    request: LabForceReminderRequest,
    actor: str = Depends(internal_auth),
) -> dict[str, Any]:
    if settings.production:
        raise HTTPException(status_code=404, detail="Not found")
    with transaction() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    UPDATE ar_cases
                    SET issued_at = now() - (:age_days * interval '1 day'),
                        due_at = now() - (:age_days * interval '1 day'),
                        status = CASE WHEN status = 'OPEN' THEN 'PAST_DUE' ELSE status END,
                        next_reminder_at = now() - interval '1 second',
                        paused_until = NULL,
                        locked_at = NULL,
                        locked_by = NULL
                    WHERE current_balance_cents > 0
                      AND status IN ('OPEN','PAST_DUE')
                    RETURNING id::text, invoice_number, current_balance_cents, due_at
                    """
                ),
                {"age_days": request.age_days},
            )
            .mappings()
            .all()
        )
        audit_entries = [dict(row) for row in rows]
        for row in audit_entries:
            logger.info(
                "Local lab reminder forced",
                extra={
                    "actor": actor,
                    "ar_case_id": row["id"],
                    "invoice_number": row["invoice_number"],
                    "age_days": request.age_days,
                },
            )
    return {"queued_cases": audit_entries, "count": len(audit_entries), "age_days": request.age_days}


@app.get("/internal/v1/ar/cases")
def read_ar_cases(
    ar_status: str | None = None,
    limit: int = 100,
    actor: str = Depends(internal_auth),
) -> dict[str, Any]:
    with transaction() as conn:
        return {"items": list_ar_cases(conn, ar_status.upper() if ar_status else None, limit)}


@app.get("/internal/v1/ar/aging")
def read_ar_aging(actor: str = Depends(internal_auth)) -> dict[str, Any]:
    with transaction() as conn:
        return ar_aging_summary(conn, datetime.now(UTC))


@app.post("/internal/v1/ar/{case_id}/pause")
def pause_ar_case(case_id: str, request: ArHoldRequest, actor: str = Depends(internal_auth)) -> dict[str, Any]:
    def action(conn: Any) -> dict[str, Any]:
        case = get_ar_case(conn, case_id, for_update=True)
        hold = create_collection_hold(
            conn,
            case=case,
            hold_type=request.hold_type,
            reason=request.reason,
            created_by=actor,
        )
        return {"case_id": case_id, "status": get_ar_case(conn, case_id)["status"], "hold_id": str(hold["id"])}
    return _idempotent(f"ar-pause:{case_id}", request, action)


@app.post("/internal/v1/ar/{case_id}/resume")
def resume_ar_case(case_id: str, request: ArResumeRequest, actor: str = Depends(internal_auth)) -> dict[str, Any]:
    def action(conn: Any) -> dict[str, Any]:
        case = get_ar_case(conn, case_id, for_update=True)
        release_collection_holds(conn, case_id, actor)
        status_value = "PAID" if int(case["current_balance_cents"]) <= 0 else "PAST_DUE"
        updated = update_ar_case(
            conn,
            case_id,
            status=status_value,
            hold_reason=None,
            paused_until=None,
            next_reminder_at=(None if status_value == "PAID" else datetime.now(UTC)),
            locked_at=None,
            locked_by=None,
            metadata={"resume_reason": request.reason, "resumed_by": actor},
        )
        return {"case_id": case_id, "status": updated["status"]}
    return _idempotent(f"ar-resume:{case_id}", request, action)


@app.post("/internal/v1/ar/{case_id}/sms-consent")
def set_sms_consent(case_id: str, request: SmsConsentRequest, actor: str = Depends(internal_auth)) -> dict[str, Any]:
    def action(conn: Any) -> dict[str, Any]:
        case = get_ar_case(conn, case_id)
        phone = str(case.get("recipient_phone_e164") or "")
        if not phone:
            raise ConflictError("A/R case has no normalized customer phone")
        consent = upsert_sms_consent(
            conn,
            organization_id=str(case["organization_id"]),
            job_id=str(case["job_id"]),
            phone_e164=phone,
            status=request.status,
            source=request.source,
            disclosure_version=request.disclosure_version,
            captured_at=datetime.now(UTC),
            evidence={"actor": actor},
        )
        return {"case_id": case_id, "phone": phone, "status": consent["status"]}
    return _idempotent(f"ar-consent:{case_id}", request, action)


@app.get("/internal/v1/messages/{thread_id}")
def read_message_thread(thread_id: str, limit: int = 50, actor: str = Depends(internal_auth)) -> dict[str, Any]:
    with transaction() as conn:
        return {"thread": get_message_thread(conn, thread_id), "messages": list_thread_messages(conn, thread_id, limit)}


@app.post("/internal/v1/messages/{thread_id}/reply")
def reply_to_message_thread(
    thread_id: str,
    request: ManualReplyRequest,
    actor: str = Depends(internal_auth),
) -> dict[str, Any]:
    def action(conn: Any) -> dict[str, Any]:
        thread = get_message_thread(conn, thread_id)
        if not thread.get("job_id"):
            raise ConflictError("Message thread is not linked to a job")
        event_id = enqueue(
            conn,
            str(thread["job_id"]),
            "SEND_MANUAL_REPLY",
            {"thread_id": thread_id, "body": request.body, "actor": actor},
        )
        return {"thread_id": thread_id, "queued": True, "outbox_event_id": event_id}
    return _idempotent(f"manual-reply:{thread_id}", request, action)


@app.get("/internal/v1/staff-alerts")
def read_staff_alerts(
    alert_status: str | None = "OPEN",
    limit: int = 100,
    actor: str = Depends(internal_auth),
) -> dict[str, Any]:
    with transaction() as conn:
        return {"items": list_staff_alerts(conn, alert_status.upper() if alert_status else None, limit)}


@app.post("/internal/v1/staff-alerts/{alert_id}")
def change_staff_alert(
    alert_id: str,
    request: StaffAlertUpdateRequest,
    actor: str = Depends(internal_auth),
) -> dict[str, Any]:
    def action(conn: Any) -> dict[str, Any]:
        updated = update_staff_alert(conn, alert_id, status=request.status, actor=actor)
        return {"alert_id": alert_id, "status": updated["status"]}
    return _idempotent(f"staff-alert:{alert_id}", request, action)


def _documenso_envelope_id(payload: dict[str, Any]) -> str | None:
    candidates = [payload, payload.get("data"), payload.get("payload"), payload.get("envelope")]
    for candidate in candidates:
        if isinstance(candidate, dict):
            value = candidate.get("envelopeId") or candidate.get("envelope_id")
            if value:
                return str(value)
            if candidate is payload.get("envelope") and candidate.get("id"):
                return str(candidate["id"])
            nested = candidate.get("envelope")
            if isinstance(nested, dict) and nested.get("id"):
                return str(nested["id"])
    return None


@app.post("/webhooks/documenso")
async def documenso_webhook(request: Request, x_documenso_secret: str = Header(default="")) -> dict[str, bool]:
    body = await request.body()
    if len(body) > settings.webhook_max_body_bytes:
        raise HTTPException(status_code=413, detail="Request body too large")
    if not verify_shared_secret(x_documenso_secret, settings.documenso_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid Documenso secret")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    event_type = str(payload.get("event") or payload.get("type") or "unknown")
    envelope_id = _documenso_envelope_id(payload)
    event_id = str(payload.get("event_id") or payload.get("eventId") or f"{event_type}:{envelope_id or 'none'}:{sha256_hex(body)}")
    with transaction() as conn:
        if not record_webhook(conn, "documenso", event_id, event_type, body):
            return {"accepted": True}
        if not envelope_id:
            finish_webhook(conn, "documenso", event_id, "IGNORED", "No envelope id")
            return {"accepted": True}
        document = get_document_by_envelope(conn, envelope_id, for_update=True)
        if not document:
            finish_webhook(conn, "documenso", event_id, "IGNORED", "Envelope is not mapped")
            return {"accepted": True}
        normalized = event_type.upper()
        if any(word in normalized for word in ("COMPLETED", "SIGNED", "EXECUTED")):
            if document["status"] in {"REJECTED", "CANCELLED", "FAILED"}:
                finish_webhook(conn, "documenso", event_id, "IGNORED", "Late completion after terminal document state")
                return {"accepted": True}
            if document["status"] != "COMPLETED":
                enqueue(
                    conn,
                    str(document["job_id"]),
                    "FINALIZE_DOCUMENT",
                    {"document_id": str(document["id"]), "provider_event_id": event_id},
                )
        elif any(word in normalized for word in ("REJECT", "DECLIN", "CANCEL")):
            if document["status"] == "COMPLETED":
                finish_webhook(conn, "documenso", event_id, "IGNORED", "Late rejection after completion")
                return {"accepted": True}
            if document["status"] not in {"PENDING", "DRAFT"}:
                finish_webhook(conn, "documenso", event_id, "IGNORED", "Document already has a terminal state")
                return {"accepted": True}
            status_value = "REJECTED" if "CANCEL" not in normalized else "CANCELLED"
            update_document(conn, str(document["id"]), status=status_value)
            job = get_job(conn, str(document["job_id"]))
            if document["kind"] == "WORK_AUTHORIZATION":
                transition_job(conn, str(job["id"]), WorkflowState.FAILED, error=f"Work Authorization {status_value.lower()}")
            elif document["kind"] == "CHANGE_ORDER" and job["state"] == WorkflowState.CHANGE_ORDER_PENDING.value:
                transition_job(conn, str(job["id"]), WorkflowState.IN_PROGRESS)
            elif document["kind"] == "COMPLETION_OF_SERVICE" and job["state"] == WorkflowState.COMPLETION_SENT.value:
                paid = total_paid_cents(conn, str(job["id"]))
                transition_job(
                    conn,
                    str(job["id"]),
                    WorkflowState.PAYMENT_REVIEW if paid > int(job["total_cents"]) else (WorkflowState.PAID if paid == int(job["total_cents"]) else WorkflowState.IN_PROGRESS),
                )
        finish_webhook(conn, "documenso", event_id, "PROCESSED")
    return {"accepted": True}


def _money(cents: int, currency: str) -> str:
    symbol = "$" if currency == "USD" else f"{currency} "
    return f"{symbol}{cents / 100:,.2f}"


@app.get("/p/complete", response_class=HTMLResponse)
def portal_complete() -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html><head><meta name='robots' content='noindex'><title>Floodman</title></head>"
        "<body><main><h1>Thank you</h1><p>Your document action was received. You may close this page.</p></main></body></html>"
    )


@app.get("/p/{token}", response_class=HTMLResponse)
def customer_portal(token: str, request: Request) -> HTMLResponse:
    remote = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")
    job_id: str | None = None
    try:
        claims = decode_portal_token(token, settings.portal_token_secret)
        job_id = claims.job_id
        with transaction() as conn:
            job = get_job(conn, claims.job_id)
            if int(job["portal_token_version"]) != claims.version:
                raise AuthenticationError("Portal link has been revoked")
            payload = portal_payload(conn, claims.job_id)
            log_portal_access(
                conn,
                job_id=claims.job_id,
                remote_hash=privacy_hash(settings.portal_token_secret, remote) if remote else None,
                user_agent_hash=privacy_hash(settings.portal_token_secret, user_agent) if user_agent else None,
                result="ALLOWED",
            )
    except (AuthenticationError, NotFoundError) as exc:
        with transaction() as conn:
            log_portal_access(
                conn,
                job_id=job_id,
                remote_hash=privacy_hash(settings.portal_token_secret, remote) if remote else None,
                user_agent_hash=privacy_hash(settings.portal_token_secret, user_agent) if user_agent else None,
                result="DENIED",
            )
        raise HTTPException(status_code=404, detail="Portal link is invalid or expired") from exc

    document_rows = []
    for document in payload["documents"]:
        action = ""
        if document.get("status") == "PENDING" and document.get("signing_url"):
            action = f"<a class='button' rel='noreferrer' href='{html.escape(str(document['signing_url']))}'>Review and sign</a>"
        document_rows.append(
            "<li><strong>{}</strong> <span>{}</span>{}</li>".format(
                html.escape(str(document["kind"]).replace("_", " ").title()),
                html.escape(str(document["status"]).title()),
                action,
            )
        )
    paid = int(payload.get("paid_cents", 0))
    remaining = max(0, int(payload["total_cents"]) - paid)
    payment_buttons: list[str] = []
    if remaining:
        for link in payload.get("payment_links") or []:
            link_remaining = int(link.get("remaining_cents") or 0)
            if not link.get("url") or link_remaining <= 0:
                continue
            label = "Pay original invoice" if link.get("kind") == "ORIGINAL_INVOICE" else "Pay signed Change Order"
            amount_text = f" ({_money(link_remaining, payload['currency'])})"
            payment_buttons.append(
                f"<a class='button pay' rel='noreferrer' href='{html.escape(str(link['url']))}'>"
                f"{html.escape(label + amount_text)}</a>"
            )
    pay_button = "".join(payment_buttons)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Floodman Customer Portal</title>
<style>
body{{font-family:system-ui,sans-serif;background:#f3f6f8;color:#17202a;margin:0}}main{{max-width:760px;margin:2rem auto;background:white;padding:2rem;border-radius:16px;box-shadow:0 12px 40px #0001}}
h1{{margin-top:0}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1rem}}.card{{background:#f7f9fa;padding:1rem;border-radius:12px}}
ul{{padding:0;list-style:none}}li{{padding:1rem 0;border-bottom:1px solid #ddd;display:flex;gap:.7rem;align-items:center;flex-wrap:wrap}}.button{{display:inline-block;padding:.7rem 1rem;border-radius:9px;background:#173f5f;color:white;text-decoration:none;margin-left:auto}}.pay{{background:#006aff;margin:1rem 0}}small{{color:#5f6b75}}
</style></head><body><main><h1>Floodman Job Portal</h1>
<p>{html.escape(payload['customer_name'])}<br>{html.escape(str(payload['service_address']['street']))}, {html.escape(str(payload['service_address']['city']))}, {html.escape(str(payload['service_address']['state']))} {html.escape(str(payload['service_address']['postal_code']))}</p>
<div class="grid"><div class="card"><small>Contract total</small><br><strong>{_money(payload['total_cents'], payload['currency'])}</strong></div><div class="card"><small>Paid</small><br><strong>{_money(paid, payload['currency'])}</strong></div><div class="card"><small>Remaining</small><br><strong>{_money(remaining, payload['currency'])}</strong></div><div class="card"><small>Status</small><br><strong>{html.escape(payload['state'].replace('_',' ').title())}</strong></div><div class="card"><small>Payment terms</small><br><strong>Due upon receipt</strong></div></div>
<p><strong>Invoice terms:</strong> the final invoice is due immediately when issued. Any unpaid balance is past due after delivery.</p>
{pay_button}<h2>Documents</h2><ul>{''.join(document_rows) or '<li>No documents yet.</li>'}</ul>
<p><small>Payments are processed by Square. Floodman does not store your card number or security code.</small></p></main></body></html>"""
    return HTMLResponse(page, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; form-action https:; base-uri 'none'"})
