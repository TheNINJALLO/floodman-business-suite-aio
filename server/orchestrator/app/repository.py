from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .schemas import CompletionRequest, ChangeOrderRequest, SyncEstimateRequest
from .ai_calling import AiCallEvent, event_dedupe_key, event_order_decision, next_call_status, stable_projection_ids
from .phone import normalize_e164
from .security import sha256_hex
from .state_machine import WorkflowState, assert_transition


class ConflictError(ValueError):
    pass


class NotFoundError(ValueError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _row(result: Any) -> dict[str, Any] | None:
    item = result.mappings().first()
    return dict(item) if item else None


def begin_idempotency(
    conn: Connection, scope: str, key: str, request_hash: str
) -> dict[str, Any] | None:
    existing = _row(
        conn.execute(
            text("""
                SELECT * FROM idempotency_keys
                WHERE scope=:scope AND idempotency_key=:key
                FOR UPDATE
            """),
            {"scope": scope, "key": key},
        )
    )
    if existing:
        if existing["request_sha256"] != request_hash:
            raise ConflictError("Idempotency key was already used with a different request")
        if existing["status"] == "COMPLETED":
            return existing["response"]
        if existing["status"] == "PROCESSING":
            raise ConflictError("A request with this idempotency key is already processing")
        conn.execute(
            text("""
                UPDATE idempotency_keys
                SET status='PROCESSING', error=NULL, response=NULL, updated_at=now()
                WHERE id=:id
            """),
            {"id": existing["id"]},
        )
        return None
    conn.execute(
        text("""
            INSERT INTO idempotency_keys(scope,idempotency_key,request_sha256)
            VALUES (:scope,:key,:request_hash)
        """),
        {"scope": scope, "key": key, "request_hash": request_hash},
    )
    return None


def complete_idempotency(conn: Connection, scope: str, key: str, response: dict[str, Any]) -> None:
    conn.execute(
        text("""
            UPDATE idempotency_keys
            SET status='COMPLETED', response=CAST(:response AS jsonb), updated_at=now()
            WHERE scope=:scope AND idempotency_key=:key
        """),
        {"scope": scope, "key": key, "response": _json(response)},
    )


def fail_idempotency(conn: Connection, scope: str, key: str, error: str) -> None:
    conn.execute(
        text("""
            UPDATE idempotency_keys
            SET status='FAILED', error=:error, updated_at=now()
            WHERE scope=:scope AND idempotency_key=:key
        """),
        {"scope": scope, "key": key, "error": error[:4000]},
    )


def enqueue(
    conn: Connection,
    aggregate_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    aggregate_type: str = "WORKFLOW_JOB",
) -> str:
    event_id = conn.execute(
        text("""
            INSERT INTO outbox_events(aggregate_type,aggregate_id,event_type,payload)
            VALUES (:aggregate_type,CAST(:aggregate_id AS uuid),:event_type,CAST(:payload AS jsonb))
            RETURNING id
        """),
        {
            "aggregate_id": aggregate_id,
            "aggregate_type": aggregate_type,
            "event_type": event_type,
            "payload": _json(payload or {}),
        },
    ).scalar_one()
    return str(event_id)


def upsert_job(conn: Connection, request: SyncEstimateRequest) -> dict[str, Any]:
    existing = _row(
        conn.execute(
            text("""
                SELECT * FROM workflow_jobs
                WHERE organization_id=:organization_id AND roomflow_job_id=:roomflow_job_id
                FOR UPDATE
            """),
            {"organization_id": request.organization_id, "roomflow_job_id": request.roomflow_job_id},
        )
    )
    customer = request.customer.model_dump(mode="json")
    property_data = request.property.model_dump(mode="json")
    estimate = request.model_dump(mode="json", exclude={"customer", "property"})
    deposit_cents = request.payment_schedule.calculate_deposit(request.total_cents)

    if existing:
        if request.revision < existing["revision"]:
            raise ConflictError("RoomFlow estimate revision is older than the stored revision")
        if request.revision == existing["revision"]:
            return existing
        if existing["state"] not in {
            WorkflowState.QUEUED.value,
            WorkflowState.ESTIMATE_SYNCED.value,
            WorkflowState.FAILED.value,
        }:
            raise ConflictError(
                "The authorization workflow has already started. Use a signed Change Order instead of overwriting the estimate."
            )
        updated = _row(
            conn.execute(
                text("""
                    UPDATE workflow_jobs SET
                        roomflow_estimate_id=:roomflow_estimate_id,
                        revision=:revision,
                        state='QUEUED',
                        customer=CAST(:customer AS jsonb),
                        property=CAST(:property AS jsonb),
                        estimate=CAST(:estimate AS jsonb),
                        invoice_number=:invoice_number,
                        total_cents=:total_cents,
                        deposit_cents=:deposit_cents,
                        currency=:currency,
                        last_error=NULL
                    WHERE id=:id
                    RETURNING *
                """),
                {
                    "id": existing["id"],
                    "roomflow_estimate_id": request.roomflow_estimate_id,
                    "revision": request.revision,
                    "customer": _json(customer),
                    "property": _json(property_data),
                    "estimate": _json(estimate),
                    "invoice_number": request.invoice_number,
                    "total_cents": request.total_cents,
                    "deposit_cents": deposit_cents,
                    "currency": request.currency,
                },
            )
        )
        enqueue(conn, str(updated["id"]), "SYNC_ESTIMATE_TO_GAUZY")
        return updated

    created = _row(
        conn.execute(
            text("""
                INSERT INTO workflow_jobs(
                    organization_id,roomflow_job_id,roomflow_estimate_id,revision,state,
                    customer,property,estimate,invoice_number,total_cents,deposit_cents,currency
                ) VALUES (
                    :organization_id,:roomflow_job_id,:roomflow_estimate_id,:revision,'QUEUED',
                    CAST(:customer AS jsonb),CAST(:property AS jsonb),CAST(:estimate AS jsonb),
                    :invoice_number,:total_cents,:deposit_cents,:currency
                ) RETURNING *
            """),
            {
                "organization_id": request.organization_id,
                "roomflow_job_id": request.roomflow_job_id,
                "roomflow_estimate_id": request.roomflow_estimate_id,
                "revision": request.revision,
                "customer": _json(customer),
                "property": _json(property_data),
                "estimate": _json(estimate),
                "invoice_number": request.invoice_number,
                "total_cents": request.total_cents,
                "deposit_cents": deposit_cents,
                "currency": request.currency,
            },
        )
    )
    enqueue(conn, str(created["id"]), "SYNC_ESTIMATE_TO_GAUZY")
    audit(conn, request.organization_id, "ROOMFLOW", request.roomflow_job_id, "JOB_CREATED", "workflow_job", str(created["id"]), {"revision": request.revision})
    return created


def get_job(conn: Connection, job_id: str, for_update: bool = False) -> dict[str, Any]:
    suffix = " FOR UPDATE" if for_update else ""
    job = _row(conn.execute(text(f"SELECT * FROM workflow_jobs WHERE id=CAST(:id AS uuid){suffix}"), {"id": job_id}))
    if not job:
        raise NotFoundError("Workflow job not found")
    return job


def transition_job(
    conn: Connection, job_id: str, target: str | WorkflowState, *, error: str | None = None, updates: dict[str, Any] | None = None
) -> dict[str, Any]:
    job = get_job(conn, job_id, for_update=True)
    assert_transition(job["state"], str(target))
    assignments = ["state=:state", "last_error=:last_error"]
    params: dict[str, Any] = {"id": job_id, "state": str(target), "last_error": error}
    allowed = {
        "gauzy_contact_id", "gauzy_estimate_id", "gauzy_invoice_id", "gauzy_project_id", "square_customer_id",
        "square_order_id", "square_invoice_id", "square_invoice_version", "square_public_url",
        "square_invoice_role", "square_final_order_id", "square_final_invoice_id",
        "square_final_invoice_version", "square_final_public_url", "final_invoice_issued_at",
        "final_invoice_due_at", "total_cents", "deposit_cents", "estimate", "portal_token_version"
    }
    for key, value in (updates or {}).items():
        if key not in allowed:
            raise ValueError(f"Unsupported workflow update field {key}")
        if key == "estimate":
            assignments.append(f"{key}=CAST(:{key} AS jsonb)")
            params[key] = _json(value)
        else:
            assignments.append(f"{key}=:{key}")
            params[key] = value
    result = _row(
        conn.execute(
            text(f"UPDATE workflow_jobs SET {', '.join(assignments)} WHERE id=CAST(:id AS uuid) RETURNING *"),
            params,
        )
    )
    audit(conn, job["organization_id"], "SYSTEM", None, "STATE_CHANGED", "workflow_job", job_id, {"from": job["state"], "to": str(target)})
    return result


def add_document(
    conn: Connection,
    job: dict[str, Any],
    kind: str,
    revision: int,
    document: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    customer = job["customer"]
    result = _row(
        conn.execute(
            text("""
                INSERT INTO workflow_documents(
                    job_id,kind,revision,status,source_url,recipient_email,recipient_name,metadata
                ) VALUES (
                    CAST(:job_id AS uuid),:kind,:revision,'QUEUED',:source_url,:email,:name,CAST(:metadata AS jsonb)
                )
                ON CONFLICT (job_id,kind,revision) DO UPDATE SET
                    source_url=CASE WHEN workflow_documents.status IN ('FAILED','QUEUED') THEN EXCLUDED.source_url ELSE workflow_documents.source_url END,
                    recipient_email=CASE WHEN workflow_documents.status IN ('FAILED','QUEUED') THEN EXCLUDED.recipient_email ELSE workflow_documents.recipient_email END,
                    recipient_name=CASE WHEN workflow_documents.status IN ('FAILED','QUEUED') THEN EXCLUDED.recipient_name ELSE workflow_documents.recipient_name END,
                    metadata=CASE WHEN workflow_documents.status IN ('FAILED','QUEUED') THEN EXCLUDED.metadata ELSE workflow_documents.metadata END,
                    status=CASE WHEN workflow_documents.status IN ('FAILED','QUEUED') THEN 'QUEUED' ELSE workflow_documents.status END
                RETURNING *
            """),
            {
                "job_id": job["id"],
                "kind": kind,
                "revision": revision,
                "source_url": document["pdf_url"],
                "email": customer["email"],
                "name": f"{customer['first_name']} {customer['last_name']}",
                "metadata": _json({**(metadata or {}), "document": document}),
            },
        )
    )
    return result


def add_change_order(conn: Connection, job_id: str, request: ChangeOrderRequest) -> dict[str, Any]:
    job = get_job(conn, job_id, for_update=True)
    if job["state"] not in {WorkflowState.DEPOSIT_PAID.value, WorkflowState.IN_PROGRESS.value, WorkflowState.CHANGE_ORDER_PENDING.value}:
        raise ConflictError("Change Orders can be created only after the deposit is paid and before completion")
    if request.revised_total_cents != job["total_cents"] + request.delta_cents:
        raise ConflictError("Change Order revised total does not match current total plus delta")
    latest = latest_document(conn, job_id, "CHANGE_ORDER")
    expected_revision = 1 if latest is None else int(latest["revision"]) + 1
    if request.revision != expected_revision:
        raise ConflictError(f"Change Order revision must be {expected_revision}")
    doc = add_document(
        conn, job, "CHANGE_ORDER", request.revision, request.document.model_dump(mode="json"),
        {"delta_cents": request.delta_cents, "revised_total_cents": request.revised_total_cents, "reason": request.reason},
    )
    if job["state"] != WorkflowState.CHANGE_ORDER_PENDING.value:
        transition_job(conn, job_id, WorkflowState.CHANGE_ORDER_PENDING)
    enqueue(conn, job_id, "SEND_DOCUMENT", {"document_id": str(doc["id"])})
    return doc


def add_completion(conn: Connection, job_id: str, request: CompletionRequest) -> dict[str, Any]:
    job = get_job(conn, job_id, for_update=True)
    if job["state"] not in {WorkflowState.DEPOSIT_PAID.value, WorkflowState.IN_PROGRESS.value, WorkflowState.PAID.value}:
        raise ConflictError("Completion of Service cannot be sent in the current workflow state")
    latest = latest_document(conn, job_id, "COMPLETION_OF_SERVICE")
    expected_revision = 1 if latest is None else int(latest["revision"]) + 1
    if request.revision != expected_revision:
        raise ConflictError(f"Completion of Service revision must be {expected_revision}")
    doc = add_document(
        conn, job, "COMPLETION_OF_SERVICE", request.revision, request.document.model_dump(mode="json"),
        {"completed_on": request.completed_on.isoformat(), "notes": request.notes},
    )
    transition_job(conn, job_id, WorkflowState.COMPLETION_SENT)
    enqueue(conn, job_id, "SEND_DOCUMENT", {"document_id": str(doc["id"])})
    return doc


def get_document(conn: Connection, document_id: str, for_update: bool = False) -> dict[str, Any]:
    suffix = " FOR UPDATE" if for_update else ""
    result = _row(conn.execute(text(f"SELECT * FROM workflow_documents WHERE id=CAST(:id AS uuid){suffix}"), {"id": document_id}))
    if not result:
        raise NotFoundError("Workflow document not found")
    return result


def get_document_by_envelope(conn: Connection, envelope_id: str, for_update: bool = False) -> dict[str, Any] | None:
    suffix = " FOR UPDATE" if for_update else ""
    return _row(conn.execute(
        text(f"SELECT * FROM workflow_documents WHERE documenso_envelope_id=:envelope_id{suffix}"),
        {"envelope_id": envelope_id},
    ))


def update_document(conn: Connection, document_id: str, **updates: Any) -> dict[str, Any]:
    allowed = {
        "status", "source_pdf_sha256", "signed_pdf_sha256", "stored_path", "documenso_envelope_id",
        "documenso_item_ids", "signing_url", "completed_at", "metadata"
    }
    assignments: list[str] = []
    params: dict[str, Any] = {"id": document_id}
    for key, value in updates.items():
        if key not in allowed:
            raise ValueError(f"Unsupported document update field {key}")
        if key in {"documenso_item_ids", "metadata"}:
            assignments.append(f"{key}=CAST(:{key} AS jsonb)")
            params[key] = _json(value)
        else:
            assignments.append(f"{key}=:{key}")
            params[key] = value
    if not assignments:
        return get_document(conn, document_id)
    return _row(conn.execute(
        text(f"UPDATE workflow_documents SET {', '.join(assignments)} WHERE id=CAST(:id AS uuid) RETURNING *"),
        params,
    ))


def get_mapping(conn: Connection, provider: str, entity_type: str, internal_id: str) -> dict[str, Any] | None:
    return _row(conn.execute(
        text("""
            SELECT * FROM external_mappings
            WHERE provider=:provider AND entity_type=:entity_type AND internal_id=:internal_id
        """),
        {"provider": provider, "entity_type": entity_type, "internal_id": internal_id},
    ))


def save_mapping(
    conn: Connection, provider: str, entity_type: str, internal_id: str, external_id: str, metadata: dict[str, Any] | None = None
) -> None:
    conn.execute(
        text("""
            INSERT INTO external_mappings(provider,entity_type,internal_id,external_id,metadata)
            VALUES (:provider,:entity_type,:internal_id,:external_id,CAST(:metadata AS jsonb))
            ON CONFLICT (provider,entity_type,internal_id) DO UPDATE SET
                external_id=EXCLUDED.external_id, metadata=EXCLUDED.metadata
        """),
        {"provider": provider, "entity_type": entity_type, "internal_id": internal_id, "external_id": external_id, "metadata": _json(metadata or {})},
    )


def claim_outbox(conn: Connection, worker_id: str, lock_seconds: int) -> dict[str, Any] | None:
    return _row(conn.execute(
        text("""
            WITH candidate AS (
                SELECT id FROM outbox_events
                WHERE status IN ('PENDING','PROCESSING')
                  AND available_at <= now()
                  AND (locked_at IS NULL OR locked_at < now() - (:lock_seconds * interval '1 second'))
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE outbox_events e
            SET status='PROCESSING', locked_at=now(), locked_by=:worker_id, attempts=e.attempts+1
            FROM candidate
            WHERE e.id=candidate.id
            RETURNING e.*
        """),
        {"worker_id": worker_id, "lock_seconds": lock_seconds},
    ))


def complete_outbox(conn: Connection, event_id: str) -> None:
    conn.execute(text("""
        UPDATE outbox_events SET status='COMPLETED', locked_at=NULL, locked_by=NULL, last_error=NULL
        WHERE id=CAST(:id AS uuid)
    """), {"id": event_id})


def retry_outbox(conn: Connection, event: dict[str, Any], error: str, max_attempts: int) -> None:
    if event["attempts"] >= max_attempts:
        status = "DEAD"
        available_at = datetime.now(UTC)
    else:
        status = "PENDING"
        delay = min(3600, 2 ** min(event["attempts"], 10))
        available_at = datetime.now(UTC) + timedelta(seconds=delay)
    conn.execute(text("""
        UPDATE outbox_events
        SET status=:status, available_at=:available_at, locked_at=NULL, locked_by=NULL, last_error=:error
        WHERE id=CAST(:id AS uuid)
    """), {"id": event["id"], "status": status, "available_at": available_at, "error": error[:4000]})
    if status == "DEAD" and str(event.get("aggregate_type") or "") == "WORKFLOW_JOB":
        conn.execute(
            text("UPDATE workflow_jobs SET last_error=:error WHERE id=:id"),
            {"id": event["aggregate_id"], "error": error[:4000]},
        )
    elif status == "DEAD" and str(event.get("aggregate_type") or "") == "CALL_INTAKE":
        conn.execute(
            text("""
                UPDATE call_intakes
                SET status='REVIEW_REQUIRED', review_status='REVIEW_REQUIRED',
                    projection_status='FAILED', projection_error=:error
                WHERE id=:id
            """),
            {"id": event["aggregate_id"], "error": error[:4000]},
        )


def record_webhook(conn: Connection, provider: str, event_id: str, event_type: str, body: bytes) -> bool:
    result = conn.execute(text("""
        INSERT INTO webhook_events(provider,provider_event_id,event_type,payload_sha256)
        VALUES (:provider,:event_id,:event_type,:payload_hash)
        ON CONFLICT (provider,provider_event_id) DO NOTHING
        RETURNING id
    """), {"provider": provider, "event_id": event_id, "event_type": event_type, "payload_hash": sha256_hex(body)})
    return result.scalar_one_or_none() is not None


def finish_webhook(conn: Connection, provider: str, event_id: str, status: str, error: str | None = None) -> None:
    conn.execute(text("""
        UPDATE webhook_events SET status=:status,error=:error,processed_at=now()
        WHERE provider=:provider AND provider_event_id=:event_id
    """), {"provider": provider, "event_id": event_id, "status": status, "error": error})


def _merge_call_values(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    result = dict(existing or {})
    for key, value in incoming.items():
        if value not in (None, "", [], {}):
            result[key] = value
    return result


def call_intake_projection(intake: dict[str, Any]) -> dict[str, Any]:
    caller = dict(intake.get("caller") or {})
    normalized = normalize_e164(str(caller.get("phone") or ""))
    caller["phone_e164"] = normalized or ""
    return {
        "intake_id": str(intake["id"]),
        "organization_id": intake["organization_id"],
        "workspace_id": intake["workspace_id"],
        "provider": intake["provider"],
        "provider_call_id": intake["provider_call_id"],
        "event_type": intake["last_event_type"],
        "event_sequence": int(intake["last_sequence"]),
        "status": intake["status"],
        "occurred_at": intake["last_event_at"],
        "started_at": intake.get("started_at"),
        "ended_at": intake.get("ended_at"),
        "caller": caller,
        "property": dict(intake.get("property") or {}),
        "service_reason": intake.get("service_reason") or "",
        "summary": intake.get("summary") or "",
        "requested_services": list(intake.get("requested_services") or []),
        "urgency": intake.get("urgency") or "NORMAL",
        "appointment": dict(intake.get("appointment") or {}),
        "consent": dict(intake.get("consent") or {}),
        "transcript_available": bool(intake.get("transcript_available")),
        "transcript_reference": intake.get("transcript_reference") or "",
        "failure_reason": intake.get("failure_reason") or "",
        "review_reasons": list(intake.get("review_reasons") or []),
        "proposed_ids": dict(intake.get("proposed_ids") or {}),
    }


def get_call_intake(conn: Connection, intake_id: str, *, for_update: bool = False) -> dict[str, Any]:
    suffix = " FOR UPDATE" if for_update else ""
    result = _row(conn.execute(
        text(f"SELECT * FROM call_intakes WHERE id=CAST(:id AS uuid){suffix}"),
        {"id": intake_id},
    ))
    if not result:
        raise NotFoundError("Call intake not found")
    return result


def ingest_call_event(conn: Connection, event: AiCallEvent, body: bytes) -> dict[str, Any]:
    """Persist a canonical call event and enqueue its latest Office projection."""

    ids = stable_projection_ids(event.provider, event.provider_call_id)
    dedupe = event_dedupe_key(event)
    payload_hash = sha256_hex(body)
    inserted = conn.execute(text("""
        INSERT INTO call_intake_events(
            provider,provider_call_id,provider_event_id,source_event_id,event_type,event_sequence,
            organization_id,workspace_id,payload_sha256,occurred_at
        ) VALUES (
            :provider,:call_id,:dedupe,:event_id,:event_type,:sequence,
            :organization_id,:workspace_id,:payload_hash,:occurred_at
        )
        ON CONFLICT DO NOTHING
        RETURNING id
    """), {
        "provider": event.provider,
        "call_id": event.provider_call_id,
        "dedupe": dedupe,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "sequence": event.event_sequence,
        "organization_id": event.organization_id,
        "workspace_id": event.workspace_id,
        "payload_hash": payload_hash,
        "occurred_at": event.occurred_at,
    }).scalar_one_or_none()
    if inserted is None:
        replay = _row(conn.execute(text("""
            SELECT payload_sha256 FROM call_intake_events
            WHERE provider=:provider AND provider_event_id=:dedupe
        """), {"provider": event.provider, "dedupe": dedupe}))
        if replay is None:
            replay = _row(conn.execute(text("""
                SELECT payload_sha256 FROM call_intake_events
                WHERE provider=:provider AND provider_call_id=:call_id
                  AND event_type=:event_type AND event_sequence=:sequence
            """), {
                "provider": event.provider,
                "call_id": event.provider_call_id,
                "event_type": event.event_type,
                "sequence": event.event_sequence,
            }))
        if replay and replay["payload_sha256"] != payload_hash:
            raise ConflictError("A call event replay used a different payload")
        return {"accepted": False, "replayed": True, "intake_id": ids["intake_id"]}

    existing = _row(conn.execute(text("""
        SELECT * FROM call_intakes
        WHERE provider=:provider AND provider_call_id=:call_id
        FOR UPDATE
    """), {"provider": event.provider, "call_id": event.provider_call_id}))
    if existing and event_order_decision(int(existing["last_sequence"]), event) == "STALE":
        conn.execute(text("""
            UPDATE call_intake_events SET status='IGNORED',processed_at=now(),error='STALE_SEQUENCE'
            WHERE id=:id
        """), {"id": inserted})
        audit(
            conn, event.organization_id, "AI_CALLING_PROVIDER", event.provider,
            "CALL_EVENT_IGNORED", "call_intake", str(existing["id"]),
            {"event_type": event.event_type, "event_sequence": event.event_sequence, "reason": "STALE_SEQUENCE"},
        )
        return {"accepted": False, "replayed": False, "stale": True, "intake_id": str(existing["id"])}

    caller = _merge_call_values((existing or {}).get("caller"), event.caller.model_dump(mode="json"))
    property_data = _merge_call_values((existing or {}).get("property"), event.property.model_dump(mode="json"))
    appointment = _merge_call_values((existing or {}).get("appointment"), event.appointment.model_dump(mode="json"))
    consent = _merge_call_values((existing or {}).get("consent"), event.consent.model_dump(mode="json"))
    requested_services = list(dict.fromkeys([
        *list((existing or {}).get("requested_services") or []),
        *[str(value)[:200] for value in event.requested_services],
    ]))
    review_reasons = list(dict.fromkeys([
        *list((existing or {}).get("review_reasons") or []),
        *[str(value)[:200] for value in event.review_reasons],
    ]))
    if existing is None and (event.event_sequence != 0 or event.event_type != "call-started"):
        review_reasons.append("OUT_OF_ORDER_INITIAL_EVENT")
    if event.identity_ambiguous:
        review_reasons.append("PROVIDER_IDENTITY_AMBIGUOUS")
    if event.caller.phone and not normalize_e164(event.caller.phone):
        review_reasons.append("INVALID_CALLER_PHONE")
    caller_email = str(event.caller.email or "").strip()
    if caller_email and (
        caller_email.count("@") != 1
        or " " in caller_email
        or not all(caller_email.split("@", 1))
    ):
        review_reasons.append("INVALID_CALLER_EMAIL")
    if event.event_type == "call-failed":
        review_reasons.append("PROVIDER_CALL_FAILED")
    review_reasons = list(dict.fromkeys(review_reasons))
    call_status = next_call_status(event, review_reasons=review_reasons)
    started_at = (existing or {}).get("started_at")
    if event.event_type == "call-started" and started_at is None:
        started_at = event.occurred_at
    ended_at = (existing or {}).get("ended_at")
    if event.event_type in {"call-ended", "call-failed"}:
        ended_at = event.occurred_at

    params = {
        "id": ids["intake_id"],
        "organization_id": event.organization_id,
        "workspace_id": event.workspace_id,
        "provider": event.provider,
        "call_id": event.provider_call_id,
        "status": call_status,
        "review_status": "REVIEW_REQUIRED" if review_reasons else "PENDING",
        "event_type": event.event_type,
        "sequence": event.event_sequence,
        "caller": _json(caller),
        "property": _json(property_data),
        "service_reason": event.service_reason or (existing or {}).get("service_reason") or "",
        "summary": event.summary or (existing or {}).get("summary") or "",
        "requested_services": _json(requested_services),
        "urgency": event.urgency or (existing or {}).get("urgency") or "NORMAL",
        "appointment": _json(appointment),
        "consent": _json(consent),
        "transcript_available": bool(event.transcript_available or (existing or {}).get("transcript_available")),
        "transcript_reference": event.transcript_reference or (existing or {}).get("transcript_reference") or "",
        "failure_reason": event.failure_reason or (existing or {}).get("failure_reason") or "",
        "review_reasons": _json(review_reasons),
        "proposed_ids": _json(ids),
        "started_at": started_at,
        "ended_at": ended_at,
        "last_event_at": event.occurred_at,
    }
    if existing:
        conn.execute(text("""
            UPDATE call_intakes SET
                organization_id=:organization_id,workspace_id=:workspace_id,status=:status,
                review_status=:review_status,last_event_type=:event_type,last_sequence=:sequence,
                caller=CAST(:caller AS jsonb),property=CAST(:property AS jsonb),service_reason=:service_reason,
                summary=:summary,requested_services=CAST(:requested_services AS jsonb),urgency=:urgency,
                appointment=CAST(:appointment AS jsonb),consent=CAST(:consent AS jsonb),
                transcript_available=:transcript_available,transcript_reference=:transcript_reference,
                failure_reason=:failure_reason,review_reasons=CAST(:review_reasons AS jsonb),
                proposed_ids=CAST(:proposed_ids AS jsonb),started_at=:started_at,ended_at=:ended_at,
                last_event_at=:last_event_at,projection_status='PENDING',projection_error=NULL
            WHERE id=CAST(:id AS uuid)
        """), params)
    else:
        conn.execute(text("""
            INSERT INTO call_intakes(
                id,organization_id,workspace_id,provider,provider_call_id,status,review_status,
                last_event_type,last_sequence,caller,property,service_reason,summary,requested_services,
                urgency,appointment,consent,transcript_available,transcript_reference,failure_reason,
                review_reasons,proposed_ids,started_at,ended_at,last_event_at
            ) VALUES (
                CAST(:id AS uuid),:organization_id,:workspace_id,:provider,:call_id,:status,:review_status,
                :event_type,:sequence,CAST(:caller AS jsonb),CAST(:property AS jsonb),:service_reason,:summary,
                CAST(:requested_services AS jsonb),:urgency,CAST(:appointment AS jsonb),CAST(:consent AS jsonb),
                :transcript_available,:transcript_reference,:failure_reason,CAST(:review_reasons AS jsonb),
                CAST(:proposed_ids AS jsonb),:started_at,:ended_at,:last_event_at
            )
        """), params)

    save_mapping(
        conn,
        event.provider,
        "call",
        ids["intake_id"],
        event.provider_call_id,
        {"last_event_type": event.event_type, "last_sequence": event.event_sequence},
    )
    intake = get_call_intake(conn, ids["intake_id"])
    projection = call_intake_projection(intake)
    enqueue(
        conn,
        ids["intake_id"],
        "PROJECT_CALL_INTAKE_TO_OFFICE",
        projection,
        aggregate_type="CALL_INTAKE",
    )
    conn.execute(text("""
        UPDATE call_intake_events SET status='PROCESSED',processed_at=now(),intake_id=CAST(:intake_id AS uuid)
        WHERE id=:event_id
    """), {"intake_id": ids["intake_id"], "event_id": inserted})
    audit(
        conn, event.organization_id, "AI_CALLING_PROVIDER", event.provider,
        "CALL_EVENT_ACCEPTED", "call_intake", ids["intake_id"],
        {"event_type": event.event_type, "event_sequence": event.event_sequence, "status": call_status,
         "review_reasons": review_reasons},
    )
    return {"accepted": True, "replayed": False, "stale": False, "intake_id": ids["intake_id"], "status": call_status}


def update_call_projection(conn: Connection, intake_id: str, result: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        key: result.get(key)
        for key in (
            "customer_id", "property_id", "job_id", "roomflow_job_id", "estimate_id", "note_id", "task_id", "appointment_id",
            "gauzy_contact_id", "gauzy_project_id",
        )
    }
    updated = _row(conn.execute(text("""
        UPDATE call_intakes SET
            customer_id=:customer_id,property_id=:property_id,job_id=:job_id,
            roomflow_job_id=:roomflow_job_id,estimate_id=:estimate_id,note_id=:note_id,
            task_id=:task_id,appointment_id=:appointment_id,
            gauzy_contact_id=COALESCE(:gauzy_contact_id,gauzy_contact_id),
            gauzy_project_id=COALESCE(:gauzy_project_id,gauzy_project_id),
            review_status=:review_status,projection_status=:projection_status,projection_error=NULL,
            projection_result=CAST(:projection_result AS jsonb)
        WHERE id=CAST(:id AS uuid)
        RETURNING *
    """), {
        "id": intake_id,
        **allowed,
        # Keep the existing SQL contract; detailed approval state lives in Office.
        "review_status": {"PENDING_APPROVAL": "PENDING", "APPROVED": "PROJECTED"}.get(
            str(result.get("review_status") or ""), result.get("review_status") or "PROJECTED"),
        "projection_status": result.get("projection_status") or "PROJECTED",
        "projection_result": _json({key: value for key, value in allowed.items() if value}),
    }))
    if not updated:
        raise NotFoundError("Call intake not found")
    return updated


def update_call_gauzy_links(
    conn: Connection,
    intake_id: str,
    *,
    gauzy_contact_id: str,
    gauzy_project_id: str | None,
) -> dict[str, Any]:
    intake = get_call_intake(conn, intake_id, for_update=True)
    customer_id = str(intake.get("customer_id") or "")
    property_id = str(intake.get("property_id") or "")
    if not customer_id:
        raise ConflictError("Call intake has no canonical customer for Floodman ERP mapping")
    save_mapping(conn, "gauzy", "call_customer", customer_id, gauzy_contact_id)
    if gauzy_project_id:
        if not property_id:
            raise ConflictError("Call intake has no canonical property for Floodman ERP mapping")
        save_mapping(conn, "gauzy", "call_property_project", property_id, gauzy_project_id)
    return _row(conn.execute(text("""
        UPDATE call_intakes SET gauzy_contact_id=:contact_id,gauzy_project_id=:project_id,
            gauzy_sync_status='SYNCED',gauzy_sync_error=NULL
        WHERE id=CAST(:id AS uuid) RETURNING *
    """), {"id": intake_id, "contact_id": gauzy_contact_id, "project_id": gauzy_project_id}))


def audit(
    conn: Connection, organization_id: str | None, actor_type: str, actor_id: str | None,
    action: str, entity_type: str, entity_id: str, metadata: dict[str, Any] | None = None
) -> None:
    conn.execute(text("""
        INSERT INTO audit_events(organization_id,actor_type,actor_id,action,entity_type,entity_id,metadata)
        VALUES (:organization_id,:actor_type,:actor_id,:action,:entity_type,:entity_id,CAST(:metadata AS jsonb))
    """), {
        "organization_id": organization_id, "actor_type": actor_type, "actor_id": actor_id,
        "action": action, "entity_type": entity_type, "entity_id": entity_id, "metadata": _json(metadata or {})
    })


def portal_payload(conn: Connection, job_id: str) -> dict[str, Any]:
    job = get_job(conn, job_id)
    documents = [dict(row) for row in conn.execute(text("""
        SELECT kind,revision,status,signing_url,completed_at
        FROM workflow_documents WHERE job_id=CAST(:job_id AS uuid)
        ORDER BY created_at DESC
    """), {"job_id": job_id}).mappings().all()]
    payments = [dict(row) for row in conn.execute(text("""
        SELECT amount_cents,currency,status,payment_type,occurred_at
        FROM workflow_payments WHERE job_id=CAST(:job_id AS uuid)
        ORDER BY created_at DESC LIMIT 20
    """), {"job_id": job_id}).mappings().all()]
    change_links = []
    for row in conn.execute(text("""
        SELECT external_id,metadata FROM external_mappings
        WHERE provider='square' AND entity_type='change_order_invoice'
          AND internal_id LIKE :prefix AND external_id NOT LIKE 'MANUAL:%'
        ORDER BY created_at
    """), {"prefix": job_id + ":%"}).mappings().all():
        metadata = dict(row["metadata"] or {})
        if metadata.get("public_url"):
            amount_cents = int(metadata.get("delta_cents", 0))
            paid_cents = recorded_invoice_paid_cents(conn, job_id, str(row["external_id"]))
            change_links.append({
                "kind": "CHANGE_ORDER",
                "invoice_id": row["external_id"],
                "url": metadata["public_url"],
                "amount_cents": amount_cents,
                "paid_cents": paid_cents,
                "remaining_cents": max(0, amount_cents - paid_cents),
            })
    payment_links = []
    if job.get("square_public_url"):
        primary_role = str(job.get("square_invoice_role") or "LEGACY")
        primary_amount = int(job["deposit_cents"] if primary_role == "DEPOSIT" else (job.get("estimate") or {}).get("total_cents", job["total_cents"]))
        primary_paid = recorded_invoice_paid_cents(conn, job_id, str(job.get("square_invoice_id") or ""))
        payment_links.append({
            "kind": "DEPOSIT_INVOICE" if primary_role == "DEPOSIT" else "ORIGINAL_INVOICE",
            "invoice_id": job.get("square_invoice_id"), "url": job["square_public_url"],
            "amount_cents": primary_amount, "paid_cents": primary_paid,
            "remaining_cents": max(0, primary_amount - primary_paid),
        })
    if job.get("square_final_public_url"):
        metadata = get_mapping(conn, "square", "final_invoice", job_id) or {}
        final_meta = dict(metadata.get("metadata") or {})
        final_amount = int(final_meta.get("amount_cents", max(0, int(job["total_cents"]) - total_paid_cents(conn, job_id))))
        final_paid = recorded_invoice_paid_cents(conn, job_id, str(job.get("square_final_invoice_id") or ""))
        payment_links.append({
            "kind": "FINAL_INVOICE", "invoice_id": job.get("square_final_invoice_id"),
            "url": job["square_final_public_url"], "amount_cents": final_amount,
            "paid_cents": final_paid, "remaining_cents": max(0, final_amount - final_paid),
        })
    payment_links.extend(change_links)
    return {
        "job_id": str(job["id"]),
        "state": job["state"],
        "customer_name": f"{job['customer']['first_name']} {job['customer']['last_name']}",
        "service_address": job["property"]["service_address"],
        "invoice_number": job["invoice_number"],
        "total_cents": job["total_cents"],
        "deposit_cents": job["deposit_cents"],
        "currency": job["currency"],
        "payment_url": job.get("square_final_public_url") or job.get("square_public_url"),
        "payment_links": payment_links,
        "documents": documents,
        "payments": payments,
        "paid_cents": total_paid_cents(conn, job_id),
        "final_invoice_issued_at": job.get("final_invoice_issued_at"),
        "final_invoice_due_at": job.get("final_invoice_due_at"),
        "payment_terms": "DUE_UPON_RECEIPT",
    }


def update_job_fields(conn: Connection, job_id: str, **updates: Any) -> dict[str, Any]:
    allowed = {
        "gauzy_contact_id", "gauzy_estimate_id", "gauzy_invoice_id", "gauzy_project_id", "square_customer_id",
        "square_order_id", "square_invoice_id", "square_invoice_version", "square_public_url",
        "square_invoice_role", "square_final_order_id", "square_final_invoice_id",
        "square_final_invoice_version", "square_final_public_url", "final_invoice_issued_at",
        "final_invoice_due_at", "total_cents", "deposit_cents", "estimate", "last_error", "portal_token_version",
    }
    assignments: list[str] = []
    params: dict[str, Any] = {"id": job_id}
    for key, value in updates.items():
        if key not in allowed:
            raise ValueError(f"Unsupported workflow update field {key}")
        if key == "estimate":
            assignments.append(f"{key}=CAST(:{key} AS jsonb)")
            params[key] = _json(value)
        else:
            assignments.append(f"{key}=:{key}")
            params[key] = value
    if not assignments:
        return get_job(conn, job_id)
    return _row(
        conn.execute(
            text(f"UPDATE workflow_jobs SET {', '.join(assignments)} WHERE id=CAST(:id AS uuid) RETURNING *"),
            params,
        )
    )


def get_job_by_square_invoice(conn: Connection, invoice_id: str) -> dict[str, Any] | None:
    direct = _row(
        conn.execute(
            text("SELECT * FROM workflow_jobs WHERE square_invoice_id=:invoice_id OR square_final_invoice_id=:invoice_id"),
            {"invoice_id": invoice_id},
        )
    )
    if direct:
        return direct
    mapping = _row(
        conn.execute(
            text("""
                SELECT internal_id FROM external_mappings
                WHERE provider='square' AND entity_type='change_order_invoice' AND external_id=:invoice_id
            """),
            {"invoice_id": invoice_id},
        )
    )
    if not mapping:
        return None
    job_id = str(mapping["internal_id"]).split(":", 1)[0]
    return get_job(conn, job_id)


def get_mapping_by_external(conn: Connection, provider: str, entity_type: str, external_id: str) -> dict[str, Any] | None:
    return _row(
        conn.execute(
            text("""
                SELECT * FROM external_mappings
                WHERE provider=:provider AND entity_type=:entity_type AND external_id=:external_id
            """),
            {"provider": provider, "entity_type": entity_type, "external_id": external_id},
        )
    )


def list_job_documents(conn: Connection, job_id: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            text("SELECT * FROM workflow_documents WHERE job_id=CAST(:job_id AS uuid) ORDER BY created_at"),
            {"job_id": job_id},
        ).mappings().all()
    ]


def latest_document(conn: Connection, job_id: str, kind: str) -> dict[str, Any] | None:
    return _row(
        conn.execute(
            text("""
                SELECT * FROM workflow_documents
                WHERE job_id=CAST(:job_id AS uuid) AND kind=:kind
                ORDER BY revision DESC LIMIT 1
            """),
            {"job_id": job_id, "kind": kind},
        )
    )


def reset_document_for_retry(conn: Connection, document_id: str) -> dict[str, Any]:
    document = get_document(conn, document_id, for_update=True)
    if document["status"] not in {"FAILED", "CANCELLED"}:
        raise ConflictError("Only failed or cancelled documents can be reset; rejected documents require a new revision")
    if document.get("documenso_envelope_id"):
        raise ConflictError("Document already has a Documenso envelope; inspect it before retrying")
    metadata = dict(document.get("metadata") or {})
    metadata["manual_retry_confirmed_at"] = datetime.now(UTC).isoformat()
    result = update_document(conn, document_id, status="QUEUED", metadata=metadata)
    enqueue(conn, str(document["job_id"]), "SEND_DOCUMENT", {"document_id": document_id})
    return result


def recorded_invoice_paid_cents(conn: Connection, job_id: str, provider_invoice_id: str) -> int:
    return int(
        conn.execute(
            text("""
                SELECT COALESCE(sum(amount_cents),0) FROM workflow_payments
                WHERE job_id=CAST(:job_id AS uuid) AND provider='square'
                  AND provider_invoice_id=:provider_invoice_id AND status='COMPLETED'
            """),
            {"job_id": job_id, "provider_invoice_id": provider_invoice_id},
        ).scalar_one()
    )


def total_paid_cents(conn: Connection, job_id: str) -> int:
    return int(
        conn.execute(
            text("""
                SELECT COALESCE(sum(amount_cents),0) FROM workflow_payments
                WHERE job_id=CAST(:job_id AS uuid) AND provider='square' AND status='COMPLETED'
            """),
            {"job_id": job_id},
        ).scalar_one()
    )


def record_payment_delta(
    conn: Connection,
    *,
    job_id: str,
    provider_invoice_id: str,
    provider_payment_id: str,
    amount_cents: int,
    currency: str,
    payment_type: str,
    occurred_at: datetime,
    payload: dict[str, Any],
) -> bool:
    if amount_cents <= 0:
        return False
    result = conn.execute(
        text("""
            INSERT INTO workflow_payments(
                job_id,provider,provider_payment_id,provider_invoice_id,amount_cents,currency,
                status,payment_type,occurred_at,payload
            ) VALUES (
                CAST(:job_id AS uuid),'square',:provider_payment_id,:provider_invoice_id,
                :amount_cents,:currency,'COMPLETED',:payment_type,:occurred_at,CAST(:payload AS jsonb)
            )
            ON CONFLICT (provider,provider_payment_id) DO NOTHING
            RETURNING id
        """),
        {
            "job_id": job_id,
            "provider_payment_id": provider_payment_id,
            "provider_invoice_id": provider_invoice_id,
            "amount_cents": amount_cents,
            "currency": currency,
            "payment_type": payment_type,
            "occurred_at": occurred_at,
            "payload": _json(payload),
        },
    )
    return result.scalar_one_or_none() is not None


def log_portal_access(
    conn: Connection, *, job_id: str | None, remote_hash: str | None, user_agent_hash: str | None, result: str
) -> None:
    conn.execute(
        text("""
            INSERT INTO portal_access_log(job_id,remote_hash,user_agent_hash,result)
            VALUES (CAST(:job_id AS uuid),:remote_hash,:user_agent_hash,:result)
        """),
        {"job_id": job_id, "remote_hash": remote_hash, "user_agent_hash": user_agent_hash, "result": result},
    )


def save_ai_report_notice(conn: Connection, report: dict[str, Any]) -> None:
    audit(
        conn,
        "floodman",
        "AI_WORKER",
        report.get("target_id"),
        "COMPETITOR_REPORT_READY",
        "competitor_report",
        str(report.get("report_id")),
        {
            "target_name": report.get("target_name"),
            "generated_at": report.get("generated_at"),
            "change_summary": report.get("change_summary") or {},
        },
    )


def list_change_order_invoice_ids(conn: Connection, job_id: str) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(
            text("""
                SELECT external_id FROM external_mappings
                WHERE provider='square' AND entity_type='change_order_invoice'
                  AND internal_id LIKE :prefix AND external_id NOT LIKE 'MANUAL:%'
                ORDER BY created_at
            """),
            {"prefix": job_id + ":%"},
        ).all()
    ]


def requeue_dead_event(conn: Connection, event_id: str) -> dict[str, Any]:
    event = _row(
        conn.execute(
            text("SELECT * FROM outbox_events WHERE id=CAST(:id AS uuid) FOR UPDATE"),
            {"id": event_id},
        )
    )
    if not event:
        raise NotFoundError("Outbox event not found")
    if event["status"] != "DEAD":
        raise ConflictError("Only dead-letter events can be requeued")
    if event["event_type"] == "SEND_DOCUMENT":
        raise ConflictError("Use the reviewed document retry endpoint for signature dispatch failures")
    result = _row(
        conn.execute(
            text("""
                UPDATE outbox_events SET
                    status='PENDING', attempts=0, available_at=now(),
                    locked_at=NULL, locked_by=NULL, last_error=NULL
                WHERE id=CAST(:id AS uuid) RETURNING *
            """),
            {"id": event_id},
        )
    )
    conn.execute(
        text("UPDATE workflow_jobs SET last_error=NULL WHERE id=:id"),
        {"id": event["aggregate_id"]},
    )
    return result


def rotate_portal_token_version(conn: Connection, job_id: str) -> dict[str, Any]:
    result = _row(
        conn.execute(
            text("""
                UPDATE workflow_jobs
                SET portal_token_version=portal_token_version+1
                WHERE id=CAST(:id AS uuid) RETURNING *
            """),
            {"id": job_id},
        )
    )
    if not result:
        raise NotFoundError("Workflow job not found")
    audit(
        conn, result["organization_id"], "SYSTEM", None, "PORTAL_LINK_ROTATED",
        "workflow_job", job_id, {"portal_token_version": result["portal_token_version"]},
    )
    return result


def claim_pending_ledger_payment(conn: Connection, job_id: str) -> dict[str, Any] | None:
    """Atomically claim one payment ledger row.

    PROCESSING rows are recoverable after ten minutes so a worker crash cannot strand
    a Square payment forever. Provider-side marker reconciliation makes the retry safe.
    """
    return _row(
        conn.execute(
            text("""
                WITH candidate AS (
                    SELECT id
                    FROM workflow_payments
                    WHERE job_id=CAST(:job_id AS uuid)
                      AND provider='square'
                      AND status='COMPLETED'
                      AND (
                          ledger_status IN ('PENDING','FAILED')
                          OR (ledger_status='PROCESSING' AND ledger_locked_at < now() - interval '10 minutes')
                      )
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE workflow_payments AS payment
                SET ledger_status='PROCESSING', ledger_locked_at=now(), ledger_error=NULL
                FROM candidate
                WHERE payment.id=candidate.id
                RETURNING payment.*
            """),
            {"job_id": job_id},
        )
    )


def mark_payment_ledger_synced(conn: Connection, payment_id: str, gauzy_payment_id: str | None) -> None:
    conn.execute(
        text("""
            UPDATE workflow_payments
            SET ledger_status='SYNCED', ledger_locked_at=NULL, gauzy_payment_id=:gauzy_id, ledger_error=NULL
            WHERE id=CAST(:id AS uuid) AND ledger_status='PROCESSING'
        """),
        {"id": payment_id, "gauzy_id": gauzy_payment_id},
    )


def mark_payment_ledger_failed(conn: Connection, payment_id: str, error: str) -> None:
    conn.execute(
        text("""
            UPDATE workflow_payments
            SET ledger_status='FAILED', ledger_locked_at=NULL, ledger_error=:error
            WHERE id=CAST(:id AS uuid) AND ledger_status='PROCESSING'
        """),
        {"id": payment_id, "error": error[:4000]},
    )

# ---------------------------------------------------------------------------
# Accounts receivable, customer messaging, consent and staff-alert persistence
# ---------------------------------------------------------------------------


def upsert_sms_consent(
    conn: Connection,
    *,
    organization_id: str,
    job_id: str | None,
    phone_e164: str,
    status: str,
    source: str,
    disclosure_version: str | None = None,
    captured_at: datetime | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = status.upper()
    if normalized not in {"UNKNOWN", "OPTED_IN", "OPTED_OUT"}:
        raise ValueError("Unsupported SMS consent status")
    now = datetime.now(UTC)
    opted_in = now if normalized == "OPTED_IN" else None
    opted_out = now if normalized == "OPTED_OUT" else None
    result = _row(
        conn.execute(
            text("""
                INSERT INTO communication_consents(
                    organization_id,job_id,phone_e164,status,source,disclosure_version,
                    captured_at,opted_in_at,opted_out_at,evidence
                ) VALUES (
                    :organization_id,CAST(:job_id AS uuid),:phone,:status,:source,:version,
                    :captured_at,:opted_in,:opted_out,CAST(:evidence AS jsonb)
                )
                ON CONFLICT (organization_id,phone_e164,channel) DO UPDATE SET
                    job_id=COALESCE(EXCLUDED.job_id,communication_consents.job_id),
                    status=CASE
                        WHEN EXCLUDED.status='UNKNOWN' THEN communication_consents.status
                        ELSE EXCLUDED.status
                    END,
                    source=CASE
                        WHEN EXCLUDED.status='UNKNOWN' THEN communication_consents.source
                        ELSE EXCLUDED.source
                    END,
                    disclosure_version=COALESCE(EXCLUDED.disclosure_version,communication_consents.disclosure_version),
                    captured_at=COALESCE(EXCLUDED.captured_at,communication_consents.captured_at),
                    opted_in_at=CASE WHEN EXCLUDED.status='OPTED_IN' THEN now() ELSE communication_consents.opted_in_at END,
                    opted_out_at=CASE WHEN EXCLUDED.status='OPTED_OUT' THEN now() ELSE communication_consents.opted_out_at END,
                    evidence=communication_consents.evidence || EXCLUDED.evidence
                WHERE EXCLUDED.source <> 'FLOODMAN_CUSTOMER_PORTAL'
                   OR communication_consents.captured_at IS NULL
                   OR EXCLUDED.captured_at > communication_consents.captured_at
                RETURNING *
            """),
            {
                "organization_id": organization_id,
                "job_id": job_id,
                "phone": phone_e164,
                "status": normalized,
                "source": source[:120],
                "version": disclosure_version,
                "captured_at": captured_at,
                "opted_in": opted_in,
                "opted_out": opted_out,
                "evidence": _json(evidence or {}),
            },
        )
    )
    return result


def get_sms_consent(conn: Connection, organization_id: str, phone_e164: str) -> dict[str, Any] | None:
    return _row(
        conn.execute(
            text("""
                SELECT * FROM communication_consents
                WHERE organization_id=:organization_id AND phone_e164=:phone AND channel='SMS'
            """),
            {"organization_id": organization_id, "phone": phone_e164},
        )
    )


def upsert_ar_case(
    conn: Connection,
    *,
    job: dict[str, Any],
    issued_at: datetime,
    due_at: datetime,
    balance_cents: int,
    recipient_phone_e164: str | None,
    customer_timezone: str,
    next_reminder_at: datetime | None,
    stage: str = "FINAL",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    customer = job["customer"]
    customer_name = f"{customer['first_name']} {customer['last_name']}".strip()
    status = "PAID" if balance_cents <= 0 else "PAST_DUE"
    return _row(
        conn.execute(
            text("""
                INSERT INTO ar_cases(
                    job_id,organization_id,invoice_number,status,stage,issued_at,due_at,
                    original_balance_cents,current_balance_cents,currency,customer_name,
                    recipient_email,recipient_phone_e164,customer_timezone,next_reminder_at,metadata
                ) VALUES (
                    CAST(:job_id AS uuid),:organization_id,:invoice_number,:status,:stage,:issued_at,:due_at,
                    :balance,:balance,:currency,:customer_name,:email,:phone,:timezone,:next_reminder,CAST(:metadata AS jsonb)
                )
                ON CONFLICT (job_id) DO UPDATE SET
                    invoice_number=EXCLUDED.invoice_number,
                    status=EXCLUDED.status,
                    stage=EXCLUDED.stage,
                    issued_at=EXCLUDED.issued_at,
                    due_at=EXCLUDED.due_at,
                    original_balance_cents=EXCLUDED.original_balance_cents,
                    current_balance_cents=EXCLUDED.current_balance_cents,
                    currency=EXCLUDED.currency,
                    customer_name=EXCLUDED.customer_name,
                    recipient_email=EXCLUDED.recipient_email,
                    recipient_phone_e164=EXCLUDED.recipient_phone_e164,
                    customer_timezone=EXCLUDED.customer_timezone,
                    reminder_index=1,
                    reminder_count=0,
                    repeat_count=0,
                    next_reminder_at=EXCLUDED.next_reminder_at,
                    last_reminder_at=NULL,
                    paused_until=NULL,
                    hold_reason=NULL,
                    promise_to_pay_date=NULL,
                    locked_at=NULL,
                    locked_by=NULL,
                    metadata=ar_cases.metadata || EXCLUDED.metadata
                RETURNING *
            """),
            {
                "job_id": str(job["id"]),
                "organization_id": job["organization_id"],
                "invoice_number": f"F-{job['invoice_number']}-FINAL",
                "status": status,
                "stage": stage,
                "issued_at": issued_at,
                "due_at": due_at,
                "balance": max(0, balance_cents),
                "currency": job["currency"],
                "customer_name": customer_name,
                "email": customer["email"],
                "phone": recipient_phone_e164,
                "timezone": customer_timezone,
                "next_reminder": next_reminder_at if balance_cents > 0 else None,
                "metadata": _json(metadata or {}),
            },
        )
    )


def get_ar_case(conn: Connection, case_id: str, for_update: bool = False) -> dict[str, Any]:
    suffix = " FOR UPDATE" if for_update else ""
    result = _row(
        conn.execute(text(f"SELECT * FROM ar_cases WHERE id=CAST(:id AS uuid){suffix}"), {"id": case_id})
    )
    if not result:
        raise NotFoundError("A/R case not found")
    return result


def get_ar_case_by_job(conn: Connection, job_id: str, for_update: bool = False) -> dict[str, Any] | None:
    suffix = " FOR UPDATE" if for_update else ""
    return _row(
        conn.execute(text(f"SELECT * FROM ar_cases WHERE job_id=CAST(:job_id AS uuid){suffix}"), {"job_id": job_id})
    )


def update_ar_case(conn: Connection, case_id: str, **updates: Any) -> dict[str, Any]:
    allowed = {
        "status", "current_balance_cents", "next_reminder_at", "reminder_index", "reminder_count",
        "repeat_count", "last_reminder_at", "last_reconciled_at", "paused_until", "hold_reason",
        "promise_to_pay_date", "assigned_to", "last_customer_message_at", "last_staff_alert_at",
        "locked_at", "locked_by", "metadata",
    }
    assignments: list[str] = []
    params: dict[str, Any] = {"id": case_id}
    for key, value in updates.items():
        if key not in allowed:
            raise ValueError(f"Unsupported A/R update field {key}")
        if key == "metadata":
            assignments.append("metadata=metadata || CAST(:metadata AS jsonb)")
            params[key] = _json(value or {})
        else:
            assignments.append(f"{key}=:{key}")
            params[key] = value
    if not assignments:
        return get_ar_case(conn, case_id)
    return _row(
        conn.execute(
            text(f"UPDATE ar_cases SET {', '.join(assignments)} WHERE id=CAST(:id AS uuid) RETURNING *"),
            params,
        )
    )


def sync_ar_case_balance(
    conn: Connection,
    *,
    job_id: str,
    balance_cents: int,
    reopen_reminder_at: datetime | None = None,
) -> dict[str, Any] | None:
    case = get_ar_case_by_job(conn, job_id, for_update=True)
    if not case:
        return None
    balance = max(0, balance_cents)
    if balance == 0:
        status = "PAID"
        next_reminder = None
        paused_until = None
    elif case["status"] in {"HOLD", "DISPUTED", "PROMISE_TO_PAY"}:
        status = case["status"]
        next_reminder = case.get("next_reminder_at")
        paused_until = case.get("paused_until")
    else:
        status = "PAST_DUE"
        next_reminder = case.get("next_reminder_at") or reopen_reminder_at
        paused_until = None
    return update_ar_case(
        conn,
        str(case["id"]),
        current_balance_cents=balance,
        status=status,
        next_reminder_at=next_reminder,
        paused_until=paused_until,
        last_reconciled_at=datetime.now(UTC),
        locked_at=None,
        locked_by=None,
    )


def claim_due_ar_case(conn: Connection, worker_id: str, lock_seconds: int = 300) -> dict[str, Any] | None:
    return _row(
        conn.execute(
            text("""
                WITH candidate AS (
                    SELECT id FROM ar_cases
                    WHERE status IN ('PAST_DUE','OPEN')
                      AND current_balance_cents > 0
                      AND next_reminder_at IS NOT NULL
                      AND next_reminder_at <= now()
                      AND (paused_until IS NULL OR paused_until <= now())
                      AND (locked_at IS NULL OR locked_at < now() - make_interval(secs => :lock_seconds))
                    ORDER BY next_reminder_at, created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE ar_cases AS c
                SET locked_at=now(),locked_by=:worker_id
                FROM candidate
                WHERE c.id=candidate.id
                RETURNING c.*
            """),
            {"worker_id": worker_id, "lock_seconds": lock_seconds},
        )
    )


def ensure_message_thread(
    conn: Connection,
    *,
    organization_id: str,
    job_id: str | None,
    ar_case_id: str | None,
    customer_phone_e164: str | None,
    customer_email: str | None,
    business_phone_e164: str | None,
) -> dict[str, Any]:
    phone = (customer_phone_e164 or "").strip() or None
    email = (customer_email or "").strip().lower() or None
    if not phone and not email:
        raise ValueError("A message thread requires a customer phone or email")
    params = {
        "organization_id": organization_id,
        "job_id": job_id,
        "case_id": ar_case_id,
        "phone": phone,
        "email": email,
        "business_phone": business_phone_e164,
    }
    existing = _row(
        conn.execute(
            text("""
                SELECT * FROM message_threads
                WHERE organization_id=:organization_id
                  AND ((:phone IS NOT NULL AND customer_phone_e164=:phone)
                    OR (:email IS NOT NULL AND customer_email=:email))
                ORDER BY CASE WHEN customer_phone_e164=:phone THEN 0 ELSE 1 END, updated_at DESC
                LIMIT 1
                FOR UPDATE
            """),
            params,
        )
    )
    if existing:
        return _row(
            conn.execute(
                text("""
                    UPDATE message_threads SET
                        job_id=COALESCE(CAST(:job_id AS uuid),job_id),
                        ar_case_id=COALESCE(CAST(:case_id AS uuid),ar_case_id),
                        customer_phone_e164=COALESCE(:phone,customer_phone_e164),
                        customer_email=COALESCE(:email,customer_email),
                        business_phone_e164=COALESCE(:business_phone,business_phone_e164),
                        status=CASE WHEN status='CLOSED' THEN 'OPEN' ELSE status END
                    WHERE id=CAST(:id AS uuid)
                    RETURNING *
                """),
                {**params, "id": str(existing["id"])},
            )
        )
    inserted = _row(
        conn.execute(
            text("""
                INSERT INTO message_threads(
                    organization_id,job_id,ar_case_id,customer_phone_e164,customer_email,business_phone_e164
                ) VALUES (
                    :organization_id,CAST(:job_id AS uuid),CAST(:case_id AS uuid),:phone,:email,:business_phone
                )
                ON CONFLICT DO NOTHING
                RETURNING *
            """),
            params,
        )
    )
    if inserted:
        return inserted
    # A concurrent creator won one of the unique keys. Re-read the canonical row.
    result = _row(
        conn.execute(
            text("""
                SELECT * FROM message_threads
                WHERE organization_id=:organization_id
                  AND ((:phone IS NOT NULL AND customer_phone_e164=:phone)
                    OR (:email IS NOT NULL AND customer_email=:email))
                ORDER BY updated_at DESC LIMIT 1
            """),
            params,
        )
    )
    if not result:
        raise RuntimeError("Message-thread reservation conflict could not be reconciled")
    return result


def get_message_thread(conn: Connection, thread_id: str, for_update: bool = False) -> dict[str, Any]:
    suffix = " FOR UPDATE" if for_update else ""
    result = _row(
        conn.execute(text(f"SELECT * FROM message_threads WHERE id=CAST(:id AS uuid){suffix}"), {"id": thread_id})
    )
    if not result:
        raise NotFoundError("Message thread not found")
    return result


def find_message_thread_by_phone(conn: Connection, phone_e164: str) -> dict[str, Any] | None:
    return _row(
        conn.execute(
            text("SELECT * FROM message_threads WHERE customer_phone_e164=:phone ORDER BY updated_at DESC LIMIT 1"),
            {"phone": phone_e164},
        )
    )


def list_open_ar_cases_by_phone(conn: Connection, phone_e164: str) -> list[dict[str, Any]]:
    """Return every unpaid, non-terminal A/R case linked to a customer phone."""

    return [
        dict(row)
        for row in conn.execute(
            text("""
                SELECT c.*
                FROM ar_cases c
                WHERE c.recipient_phone_e164=:phone
                  AND c.current_balance_cents > 0
                  AND c.status NOT IN ('PAID','CLOSED')
                ORDER BY c.due_at,c.created_at
            """),
            {"phone": phone_e164},
        ).mappings().all()
    ]


def update_message_thread(conn: Connection, thread_id: str, **updates: Any) -> dict[str, Any]:
    allowed = {"status", "assigned_to", "last_inbound_at", "last_outbound_at", "job_id", "ar_case_id"}
    assignments: list[str] = []
    params: dict[str, Any] = {"id": thread_id}
    for key, value in updates.items():
        if key not in allowed:
            raise ValueError(f"Unsupported message-thread field {key}")
        if key in {"job_id", "ar_case_id"}:
            assignments.append(f"{key}=CAST(:{key} AS uuid)")
        else:
            assignments.append(f"{key}=:{key}")
        params[key] = value
    if not assignments:
        return get_message_thread(conn, thread_id)
    return _row(
        conn.execute(
            text(f"UPDATE message_threads SET {', '.join(assignments)} WHERE id=CAST(:id AS uuid) RETURNING *"),
            params,
        )
    )


def record_message_event(
    conn: Connection,
    *,
    thread_id: str,
    job_id: str | None,
    ar_case_id: str | None,
    direction: str,
    channel: str,
    provider: str,
    provider_message_id: str | None,
    message_kind: str,
    body: str,
    status: str,
    occurred_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = _row(
        conn.execute(
            text("""
                INSERT INTO message_events(
                    thread_id,job_id,ar_case_id,direction,channel,provider,provider_message_id,
                    message_kind,body,status,occurred_at,metadata
                ) VALUES (
                    CAST(:thread_id AS uuid),CAST(:job_id AS uuid),CAST(:case_id AS uuid),:direction,:channel,
                    :provider,:provider_id,:kind,:body,:status,COALESCE(:occurred_at,now()),CAST(:metadata AS jsonb)
                )
                ON CONFLICT (provider,provider_message_id) DO UPDATE SET
                    status=EXCLUDED.status,
                    metadata=message_events.metadata || EXCLUDED.metadata
                RETURNING *
            """),
            {
                "thread_id": thread_id,
                "job_id": job_id,
                "case_id": ar_case_id,
                "direction": direction,
                "channel": channel,
                "provider": provider,
                "provider_id": provider_message_id,
                "kind": message_kind,
                "body": body[:5000],
                "status": status,
                "occurred_at": occurred_at,
                "metadata": _json(metadata or {}),
            },
        )
    )
    stamp_field = "last_inbound_at" if direction == "INBOUND" else "last_outbound_at"
    update_message_thread(conn, thread_id, **{stamp_field: occurred_at or datetime.now(UTC)})
    return result


def update_message_delivery(
    conn: Connection,
    *,
    provider: str,
    provider_message_id: str,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    return _row(
        conn.execute(
            text("""
                UPDATE message_events SET
                    status=:status,error_code=:error_code,error_message=:error_message,
                    metadata=metadata || CAST(:metadata AS jsonb)
                WHERE provider=:provider AND provider_message_id=:provider_id
                RETURNING *
            """),
            {
                "provider": provider,
                "provider_id": provider_message_id,
                "status": status,
                "error_code": error_code,
                "error_message": (error_message or "")[:2000] or None,
                "metadata": _json(metadata or {}),
            },
        )
    )


def list_thread_messages(conn: Connection, thread_id: str, limit: int = 20) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            text("""
                SELECT * FROM message_events WHERE thread_id=CAST(:thread_id AS uuid)
                ORDER BY occurred_at DESC LIMIT :limit
            """),
            {"thread_id": thread_id, "limit": max(1, min(limit, 100))},
        ).mappings().all()
    ]


def count_recent_outbound_sms(conn: Connection, thread_id: str, days: int = 7) -> int:
    return int(
        conn.execute(
            text("""
                SELECT count(*) FROM message_events
                WHERE thread_id=CAST(:thread_id AS uuid) AND direction='OUTBOUND' AND channel='SMS'
                  AND message_kind='PAST_DUE_REMINDER'
                  AND status NOT IN ('FAILED','SUPPRESSED')
                  AND occurred_at >= now() - make_interval(days => :days)
            """),
            {"thread_id": thread_id, "days": days},
        ).scalar_one()
    )


def create_collection_hold(
    conn: Connection,
    *,
    case: dict[str, Any],
    hold_type: str,
    reason: str,
    created_by: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = _row(
        conn.execute(
            text("""
                INSERT INTO collection_holds(ar_case_id,job_id,hold_type,reason,created_by,metadata)
                VALUES (CAST(:case_id AS uuid),CAST(:job_id AS uuid),:hold_type,:reason,:created_by,CAST(:metadata AS jsonb))
                ON CONFLICT (ar_case_id,hold_type) WHERE active=true DO UPDATE SET
                    reason=EXCLUDED.reason,
                    created_by=EXCLUDED.created_by,
                    metadata=collection_holds.metadata || EXCLUDED.metadata
                RETURNING *
            """),
            {
                "case_id": str(case["id"]),
                "job_id": str(case["job_id"]),
                "hold_type": hold_type,
                "reason": reason[:4000],
                "created_by": created_by[:200],
                "metadata": _json(metadata or {}),
            },
        )
    )
    status = "DISPUTED" if hold_type in {"DISPUTE", "LEGAL"} else "HOLD"
    update_ar_case(
        conn,
        str(case["id"]),
        status=status,
        next_reminder_at=None,
        hold_reason=reason[:2000],
        locked_at=None,
        locked_by=None,
    )
    return result


def release_collection_holds(conn: Connection, case_id: str, released_by: str) -> int:
    result = conn.execute(
        text("""
            UPDATE collection_holds SET active=false,released_by=:released_by,released_at=now()
            WHERE ar_case_id=CAST(:case_id AS uuid) AND active=true
        """),
        {"case_id": case_id, "released_by": released_by[:200]},
    )
    return int(result.rowcount or 0)


def create_payment_promise(
    conn: Connection,
    *,
    case: dict[str, Any],
    promised_date: Any,
    promised_amount_cents: int | None,
    source_message_id: str | None,
    created_by: str,
    paused_until: datetime,
) -> dict[str, Any]:
    conn.execute(
        text("UPDATE payment_promises SET status='CANCELLED',resolved_at=now() WHERE ar_case_id=CAST(:id AS uuid) AND status='ACTIVE'"),
        {"id": str(case["id"])},
    )
    promise = _row(
        conn.execute(
            text("""
                INSERT INTO payment_promises(
                    ar_case_id,job_id,promised_date,promised_amount_cents,source_message_id,created_by
                ) VALUES (
                    CAST(:case_id AS uuid),CAST(:job_id AS uuid),:promised_date,:amount,CAST(:source_id AS uuid),:created_by
                ) RETURNING *
            """),
            {
                "case_id": str(case["id"]),
                "job_id": str(case["job_id"]),
                "promised_date": promised_date,
                "amount": promised_amount_cents,
                "source_id": source_message_id,
                "created_by": created_by[:200],
            },
        )
    )
    update_ar_case(
        conn,
        str(case["id"]),
        status="PROMISE_TO_PAY",
        promise_to_pay_date=promised_date,
        paused_until=paused_until,
        next_reminder_at=paused_until,
        locked_at=None,
        locked_by=None,
    )
    return promise


def mark_missed_promises(conn: Connection, today: Any) -> list[dict[str, Any]]:
    rows = [
        dict(row)
        for row in conn.execute(
            text("""
                UPDATE payment_promises SET status='MISSED',resolved_at=now()
                WHERE status='ACTIVE' AND promised_date < :today
                RETURNING *
            """),
            {"today": today},
        ).mappings().all()
    ]
    for row in rows:
        case = get_ar_case(conn, str(row["ar_case_id"]), for_update=True)
        if int(case["current_balance_cents"]) > 0:
            update_ar_case(
                conn,
                str(case["id"]),
                status="PAST_DUE",
                paused_until=None,
                next_reminder_at=datetime.now(UTC),
                hold_reason=None,
            )
    return rows


def record_ai_message_decision(
    conn: Connection,
    *,
    thread_id: str,
    inbound_message_id: str,
    provider: str,
    model: str | None,
    decision: dict[str, Any],
    policy_result: str,
) -> dict[str, Any]:
    return _row(
        conn.execute(
            text("""
                INSERT INTO ai_message_decisions(
                    thread_id,inbound_message_id,provider,model,intent,risk_level,confidence,
                    proposed_action,reply_draft,human_review_required,policy_result,structured_output
                ) VALUES (
                    CAST(:thread_id AS uuid),CAST(:message_id AS uuid),:provider,:model,:intent,:risk,:confidence,
                    :action,:reply,:human,:policy,CAST(:output AS jsonb)
                )
                ON CONFLICT (inbound_message_id) DO UPDATE SET
                    policy_result=EXCLUDED.policy_result,
                    structured_output=EXCLUDED.structured_output
                RETURNING *
            """),
            {
                "thread_id": thread_id,
                "message_id": inbound_message_id,
                "provider": provider,
                "model": model,
                "intent": str(decision.get("intent") or "UNKNOWN")[:100],
                "risk": str(decision.get("risk_level") or "HIGH")[:20],
                "confidence": float(decision.get("confidence") or 0),
                "action": str(decision.get("proposed_action") or "NO_ACTION")[:100],
                "reply": str(decision.get("reply_draft") or "")[:5000],
                "human": bool(decision.get("human_review_required", True)),
                "policy": policy_result[:500],
                "output": _json(decision),
            },
        )
    )


def create_staff_alert(
    conn: Connection,
    *,
    organization_id: str,
    job_id: str | None,
    ar_case_id: str | None,
    thread_id: str | None,
    alert_type: str,
    severity: str,
    title: str,
    body: str,
    dedupe_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _row(
        conn.execute(
            text("""
                INSERT INTO staff_alerts(
                    organization_id,job_id,ar_case_id,thread_id,alert_type,severity,title,body,dedupe_key,metadata
                ) VALUES (
                    :organization_id,CAST(:job_id AS uuid),CAST(:case_id AS uuid),CAST(:thread_id AS uuid),
                    :alert_type,:severity,:title,:body,:dedupe_key,CAST(:metadata AS jsonb)
                )
                ON CONFLICT (dedupe_key) DO UPDATE SET
                    severity=EXCLUDED.severity,
                    title=EXCLUDED.title,
                    body=EXCLUDED.body,
                    metadata=staff_alerts.metadata || EXCLUDED.metadata
                RETURNING *
            """),
            {
                "organization_id": organization_id,
                "job_id": job_id,
                "case_id": ar_case_id,
                "thread_id": thread_id,
                "alert_type": alert_type[:100],
                "severity": severity,
                "title": title[:300],
                "body": body[:5000],
                "dedupe_key": dedupe_key[:300] if dedupe_key else None,
                "metadata": _json(metadata or {}),
            },
        )
    )


def list_ar_cases(conn: Connection, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    where = "WHERE status=:status" if status else ""
    return [
        dict(row)
        for row in conn.execute(
            text(f"SELECT * FROM ar_cases {where} ORDER BY due_at,created_at LIMIT :limit"),
            {"status": status, "limit": max(1, min(limit, 500))},
        ).mappings().all()
    ]


def ar_aging_summary(
    conn: Connection,
    now: datetime,
    organization_id: str | None = None,
) -> dict[str, Any]:
    organization_filter = "WHERE organization_id=:organization_id" if organization_id else ""
    row = conn.execute(
        text(f"""
            SELECT
                count(*) FILTER (WHERE current_balance_cents > 0) AS open_count,
                COALESCE(sum(current_balance_cents) FILTER (WHERE current_balance_cents > 0),0) AS open_cents,
                count(*) FILTER (WHERE current_balance_cents > 0 AND CAST(:now AS timestamptz) < due_at + interval '8 days') AS days_0_7_count,
                COALESCE(sum(current_balance_cents) FILTER (WHERE current_balance_cents > 0 AND CAST(:now AS timestamptz) < due_at + interval '8 days'),0) AS days_0_7_cents,
                count(*) FILTER (WHERE current_balance_cents > 0 AND CAST(:now AS timestamptz) >= due_at + interval '8 days' AND CAST(:now AS timestamptz) < due_at + interval '15 days') AS days_8_14_count,
                COALESCE(sum(current_balance_cents) FILTER (WHERE current_balance_cents > 0 AND CAST(:now AS timestamptz) >= due_at + interval '8 days' AND CAST(:now AS timestamptz) < due_at + interval '15 days'),0) AS days_8_14_cents,
                count(*) FILTER (WHERE current_balance_cents > 0 AND CAST(:now AS timestamptz) >= due_at + interval '15 days' AND CAST(:now AS timestamptz) < due_at + interval '31 days') AS days_15_30_count,
                COALESCE(sum(current_balance_cents) FILTER (WHERE current_balance_cents > 0 AND CAST(:now AS timestamptz) >= due_at + interval '15 days' AND CAST(:now AS timestamptz) < due_at + interval '31 days'),0) AS days_15_30_cents,
                count(*) FILTER (WHERE current_balance_cents > 0 AND CAST(:now AS timestamptz) >= due_at + interval '31 days') AS days_31_plus_count,
                COALESCE(sum(current_balance_cents) FILTER (WHERE current_balance_cents > 0 AND CAST(:now AS timestamptz) >= due_at + interval '31 days'),0) AS days_31_plus_cents,
                count(*) FILTER (WHERE status='DISPUTED') AS disputed_count,
                count(*) FILTER (WHERE status='PROMISE_TO_PAY') AS promise_count
            FROM ar_cases
            {organization_filter}
        """),
        {"now": now, "organization_id": organization_id},
    ).mappings().one()
    return {key: int(value or 0) for key, value in dict(row).items()}


def begin_ar_digest(conn: Connection, organization_id: str, local_date: Any) -> dict[str, Any] | None:
    return _row(
        conn.execute(
            text("""
                INSERT INTO ar_digest_runs(organization_id,local_date)
                VALUES (:organization_id,:local_date)
                ON CONFLICT (organization_id,local_date) DO NOTHING
                RETURNING *
            """),
            {"organization_id": organization_id, "local_date": local_date},
        )
    )


def finish_ar_digest(conn: Connection, run_id: str, status: str, summary: dict[str, Any], error: str | None = None) -> None:
    conn.execute(
        text("""
            UPDATE ar_digest_runs SET status=:status,summary=CAST(:summary AS jsonb),error=:error,completed_at=now()
            WHERE id=CAST(:id AS uuid)
        """),
        {"id": run_id, "status": status, "summary": _json(summary), "error": (error or "")[:4000] or None},
    )


def signed_positive_change_order_cents(conn: Connection, job_id: str) -> int:
    return int(
        conn.execute(
            text("""
                SELECT COALESCE(sum((metadata->>'delta_cents')::bigint),0)
                FROM workflow_documents
                WHERE job_id=CAST(:job_id AS uuid) AND kind='CHANGE_ORDER' AND status='COMPLETED'
                  AND COALESCE((metadata->>'delta_cents')::bigint,0) > 0
            """),
            {"job_id": job_id},
        ).scalar_one()
    )


def positive_change_orders_missing_invoice(conn: Connection, job_id: str) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(
            text("""
                SELECT d.id
                FROM workflow_documents d
                WHERE d.job_id=CAST(:job_id AS uuid) AND d.kind='CHANGE_ORDER' AND d.status='COMPLETED'
                  AND COALESCE((d.metadata->>'delta_cents')::bigint,0) > 0
                  AND NOT EXISTS (
                      SELECT 1 FROM external_mappings m
                      WHERE m.provider='square' AND m.entity_type='change_order_invoice'
                        AND m.internal_id=concat(:job_prefix,d.id::text)
                  )
            """),
            {"job_id": job_id, "job_prefix": job_id + ":"},
        ).all()
    ]


def get_message_event(conn: Connection, message_id: str) -> dict[str, Any]:
    result = _row(
        conn.execute(
            text("SELECT * FROM message_events WHERE id=CAST(:id AS uuid)"),
            {"id": message_id},
        )
    )
    if not result:
        raise NotFoundError("Message event not found")
    return result


def reserve_outbound_message(
    conn: Connection,
    *,
    thread_id: str,
    job_id: str | None,
    ar_case_id: str | None,
    channel: str,
    provider: str,
    message_kind: str,
    body: str,
    dedupe_key: str,
    metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Reserve one outbound delivery exactly once.

    The database dedupe key is set before any provider request. A worker retry therefore
    observes the same reservation and does not produce a second customer message.
    """
    inserted = _row(
        conn.execute(
            text("""
                INSERT INTO message_events(
                    thread_id,job_id,ar_case_id,direction,channel,provider,dedupe_key,
                    message_kind,body,status,metadata
                ) VALUES (
                    CAST(:thread_id AS uuid),CAST(:job_id AS uuid),CAST(:case_id AS uuid),
                    'OUTBOUND',:channel,:provider,:dedupe_key,:kind,:body,'QUEUED',CAST(:metadata AS jsonb)
                )
                ON CONFLICT (dedupe_key) DO NOTHING
                RETURNING *
            """),
            {
                "thread_id": thread_id,
                "job_id": job_id,
                "case_id": ar_case_id,
                "channel": channel,
                "provider": provider,
                "dedupe_key": dedupe_key[:300],
                "kind": message_kind[:100],
                "body": body[:5000],
                "metadata": _json(metadata or {}),
            },
        )
    )
    if inserted:
        return inserted, True
    existing = _row(
        conn.execute(
            text("SELECT * FROM message_events WHERE dedupe_key=:dedupe_key"),
            {"dedupe_key": dedupe_key[:300]},
        )
    )
    if not existing:  # pragma: no cover - database consistency guard
        raise RuntimeError("Message reservation conflict did not return an existing row")
    return existing, False


def mark_message_sending(conn: Connection, message_id: str) -> dict[str, Any]:
    result = _row(
        conn.execute(
            text("""
                UPDATE message_events
                SET status='SENDING',error_code=NULL,error_message=NULL
                WHERE id=CAST(:id AS uuid) AND status IN ('QUEUED','FAILED')
                RETURNING *
            """),
            {"id": message_id},
        )
    )
    return result or get_message_event(conn, message_id)


def mark_message_sent(
    conn: Connection,
    *,
    message_id: str,
    provider_message_id: str,
    status: str = "SENT",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = _row(
        conn.execute(
            text("""
                UPDATE message_events SET
                    provider_message_id=:provider_id,status=:status,
                    metadata=metadata || CAST(:metadata AS jsonb),error_code=NULL,error_message=NULL
                WHERE id=CAST(:id AS uuid)
                RETURNING *
            """),
            {
                "id": message_id,
                "provider_id": provider_message_id[:200],
                "status": status,
                "metadata": _json(metadata or {}),
            },
        )
    )
    if not result:
        raise NotFoundError("Message event not found")
    update_message_thread(conn, str(result["thread_id"]), last_outbound_at=datetime.now(UTC))
    return result


def mark_message_failed(
    conn: Connection,
    *,
    message_id: str,
    error_code: str,
    error_message: str,
    suppress: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = _row(
        conn.execute(
            text("""
                UPDATE message_events SET
                    status=:status,error_code=:error_code,error_message=:error_message,
                    metadata=metadata || CAST(:metadata AS jsonb)
                WHERE id=CAST(:id AS uuid)
                RETURNING *
            """),
            {
                "id": message_id,
                "status": "SUPPRESSED" if suppress else "FAILED",
                "error_code": error_code[:100],
                "error_message": error_message[:2000],
                "metadata": _json(metadata or {}),
            },
        )
    )
    if not result:
        raise NotFoundError("Message event not found")
    return result


def get_staff_alert(conn: Connection, alert_id: str) -> dict[str, Any]:
    result = _row(
        conn.execute(
            text("SELECT * FROM staff_alerts WHERE id=CAST(:id AS uuid)"),
            {"id": alert_id},
        )
    )
    if not result:
        raise NotFoundError("Staff alert not found")
    return result


def list_staff_alerts(conn: Connection, status: str | None = "OPEN", limit: int = 100) -> list[dict[str, Any]]:
    where = "WHERE status=:status" if status else ""
    return [
        dict(row)
        for row in conn.execute(
            text(f"SELECT * FROM staff_alerts {where} ORDER BY created_at DESC LIMIT :limit"),
            {"status": status, "limit": max(1, min(limit, 500))},
        ).mappings().all()
    ]


def update_staff_alert(conn: Connection, alert_id: str, *, status: str, actor: str) -> dict[str, Any]:
    normalized = status.upper()
    if normalized not in {"OPEN", "ACKNOWLEDGED", "RESOLVED"}:
        raise ValueError("Unsupported staff alert status")
    result = _row(
        conn.execute(
            text("""
                UPDATE staff_alerts SET
                    status=:status,
                    acknowledged_at=CASE WHEN :status='ACKNOWLEDGED' THEN now() ELSE acknowledged_at END,
                    resolved_at=CASE WHEN :status='RESOLVED' THEN now() ELSE resolved_at END,
                    assigned_to=COALESCE(assigned_to,:actor)
                WHERE id=CAST(:id AS uuid)
                RETURNING *
            """),
            {"id": alert_id, "status": normalized, "actor": actor[:200]},
        )
    )
    if not result:
        raise NotFoundError("Staff alert not found")
    return result


def unlock_ar_case(conn: Connection, case_id: str, *, next_reminder_at: datetime | None = None) -> dict[str, Any]:
    return update_ar_case(
        conn,
        case_id,
        locked_at=None,
        locked_by=None,
        **({"next_reminder_at": next_reminder_at} if next_reminder_at is not None else {}),
    )


def organization_ids_with_ar_cases(conn: Connection) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(text("SELECT DISTINCT organization_id FROM ar_cases ORDER BY organization_id")).all()
    ]


def mark_staff_alert_delivery(
    conn: Connection,
    alert_id: str,
    *,
    delivered: bool,
    metadata: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    result = _row(
        conn.execute(
            text("""
                UPDATE staff_alerts SET
                    metadata=metadata || CAST(:metadata AS jsonb)
                WHERE id=CAST(:id AS uuid)
                RETURNING *
            """),
            {
                "id": alert_id,
                "metadata": _json({
                    **(metadata or {}),
                    "delivery_status": "DELIVERED" if delivered else "FAILED",
                    "delivered_at": datetime.now(UTC).isoformat() if delivered else None,
                    "delivery_error": (error or "")[:2000] or None,
                }),
            },
        )
    )
    if not result:
        raise NotFoundError("Staff alert not found")
    return result
