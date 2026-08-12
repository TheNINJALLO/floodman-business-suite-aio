from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .adapters.documenso import DocumensoClient
from .adapters.gauzy import GauzyClient
from .adapters.safe_fetch import fetch_pdf
from .adapters.square import SquareClient
from .ar import first_reminder_at
from .config import Settings
from .db import transaction
from .repository import (
    audit,
    enqueue,
    get_document,
    get_job,
    get_job_by_square_invoice,
    get_mapping,
    latest_document,
    mark_payment_ledger_failed,
    mark_payment_ledger_synced,
    list_change_order_invoice_ids,
    list_job_documents,
    claim_pending_ledger_payment,
    create_collection_hold,
    create_staff_alert,
    get_ar_case_by_job,
    record_payment_delta,
    recorded_invoice_paid_cents,
    save_mapping,
    total_paid_cents,
    transition_job,
    upsert_ar_case,
    upsert_sms_consent,
    sync_ar_case_balance,
    signed_positive_change_order_cents,
    positive_change_orders_missing_invoice,
    update_document,
    update_job_fields,
)
from .state_machine import WorkflowState
from .phone import normalize_e164
from .receivables import AmbiguousDeliveryError, ReceivablesManager
from .storage import ImmutableStorage

logger = logging.getLogger(__name__)


class PermanentEventError(RuntimeError):
    """An event that must not be automatically retried without human review."""


class WorkflowService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.gauzy = GauzyClient(settings)
        self.square = SquareClient(settings)
        self.documenso = DocumensoClient(settings)
        self.storage = ImmutableStorage(settings.documents_path)
        self.receivables = ReceivablesManager(settings)

    def close(self) -> None:
        self.gauzy.close()
        self.square.close()
        self.documenso.close()
        self.receivables.close()

    def handle(self, event: dict[str, Any]) -> None:
        handlers = {
            "SYNC_ESTIMATE_TO_GAUZY": self.sync_estimate_to_gauzy,
            "SEND_DOCUMENT": self.send_document,
            "FINALIZE_DOCUMENT": self.finalize_document,
            "CREATE_SQUARE_INVOICE": self.create_square_invoice,
            "CREATE_CHANGE_ORDER_INVOICE": self.create_change_order_invoice,
            "PROCESS_SQUARE_EVENT": self.process_square_event,
            "RECONCILE_JOB_PAYMENTS": self.reconcile_job_payments,
            "CREATE_FINAL_INVOICE": self.create_final_invoice,
            "SEND_INITIAL_INVOICE": self.send_initial_invoice,
            "SEND_AR_REMINDER": self.send_ar_reminder,
            "PROCESS_INBOUND_MESSAGE": self.process_inbound_message,
            "SEND_STAFF_ALERT": self.send_staff_alert,
            "SEND_PAYMENT_CONFIRMATION": self.send_payment_confirmation,
            "SEND_HELP_REPLY": self.send_help_reply,
            "SEND_MANUAL_REPLY": self.send_manual_reply,
        }
        event_type = str(event["event_type"])
        handler = handlers.get(event_type)
        if handler is None:
            raise PermanentEventError(f"Unknown outbox event type {event_type}")
        handler(str(event["aggregate_id"]), dict(event.get("payload") or {}))

    def sync_estimate_to_gauzy(self, job_id: str, payload: dict[str, Any]) -> None:
        with transaction() as conn:
            job = get_job(conn, job_id)
        if job["state"] == WorkflowState.ESTIMATE_SYNCED.value:
            return
        if job["state"] != WorkflowState.QUEUED.value:
            raise PermanentEventError(f"Cannot synchronize estimate while job is {job['state']}")

        contact = self.gauzy.ensure_contact(job["customer"], job["property"])
        contact_id = str(contact.get("id") or "")
        if not contact_id:
            raise RuntimeError("Gauzy contact response did not include id")

        project_id = ""
        project_warning = ""
        try:
            project = self.gauzy.ensure_property_project(job, contact_id=contact_id)
            project_id = str((project or {}).get("id") or "")
        except Exception as exc:
            # A deployment may disable Gauzy project creation while still allowing
            # contacts and invoices. Keep the financial workflow moving, but retain
            # a visible warning so the property can be linked by an owner later.
            project_warning = str(exc)
            logger.warning("Gauzy property project could not be created for job %s: %s", job_id, exc)

        estimate = self.gauzy.create_estimate(job, contact_id, project_id or None)
        estimate_id = str(estimate.get("id") or "")
        if not estimate_id:
            raise RuntimeError("Gauzy estimate response did not include id")

        with transaction() as conn:
            current = get_job(conn, job_id, for_update=True)
            if current["state"] == WorkflowState.ESTIMATE_SYNCED.value:
                return
            save_mapping(conn, "gauzy", "contact", str(current["id"]), contact_id)
            save_mapping(conn, "gauzy", "estimate", str(current["id"]), estimate_id)
            if project_id:
                save_mapping(conn, "gauzy", "project", str(current["id"]), project_id)
            update_job_fields(
                conn,
                job_id,
                gauzy_contact_id=contact_id,
                gauzy_estimate_id=estimate_id,
                gauzy_project_id=project_id or None,
            )
            current = transition_job(conn, job_id, WorkflowState.ESTIMATE_SYNCED)
            authorization = current["estimate"].get("authorization")
            if not isinstance(authorization, dict):
                raise PermanentEventError("RoomFlow estimate is missing its Work Authorization document")
            from .repository import add_document

            document = add_document(
                conn,
                current,
                "WORK_AUTHORIZATION",
                int(current["revision"]),
                authorization,
                {"estimate_sha256": current["estimate"].get("estimate_sha256")},
            )
            enqueue(conn, job_id, "SEND_DOCUMENT", {"document_id": str(document["id"])})
            audit(
                conn,
                current["organization_id"],
                "SYSTEM",
                None,
                "ESTIMATE_SYNCED",
                "workflow_job",
                job_id,
                {
                    "gauzy_contact_id": contact_id,
                    "gauzy_estimate_id": estimate_id,
                    "gauzy_project_id": project_id or None,
                    "project_warning": project_warning or None,
                },
            )

    def send_document(self, job_id: str, payload: dict[str, Any]) -> None:
        document_id = str(payload.get("document_id") or "")
        if not document_id:
            raise PermanentEventError("SEND_DOCUMENT event is missing document_id")
        with transaction() as conn:
            document = get_document(conn, document_id)
            job = get_job(conn, job_id)
        if document["status"] in {"PENDING", "COMPLETED"}:
            return
        if document["status"] == "DRAFT" and not document.get("documenso_envelope_id"):
            raise PermanentEventError(
                "Documenso create result is ambiguous. Inspect Documenso, then reset this document manually."
            )
        if document["status"] != "QUEUED":
            raise PermanentEventError(f"Document {document_id} cannot be sent while status is {document['status']}")

        source = fetch_pdf(
            str(document["source_url"]),
            self.settings.roomflow_document_hosts,
            self.settings.max_document_bytes,
            require_https=self.settings.document_require_https,
            allow_private=self.settings.allow_private_document_hosts,
        )
        source_path, source_hash = self.storage.store(
            job_id=job_id,
            kind=document["kind"],
            revision=int(document["revision"]),
            body=source.body,
            signed=False,
        )
        metadata = dict(document.get("metadata") or {})
        metadata.update(
            {
                "source_stored_path": source_path,
                "dispatch_started_at": datetime.now(UTC).isoformat(),
                "source_final_url": source.url,
            }
        )
        with transaction() as conn:
            update_document(
                conn,
                document_id,
                status="DRAFT",
                source_pdf_sha256=source_hash,
                metadata=metadata,
            )

        spec = metadata.get("document") or {}
        try:
            result = self.documenso.create_and_distribute(
                external_id=f"floodman:{document_id}",
                title=str(spec.get("title") or document["kind"].replace("_", " ").title()),
                recipient_email=document["recipient_email"],
                recipient_name=document["recipient_name"],
                fields=list(spec.get("fields") or []),
                pdf=source.body,
                filename=f"{document['kind'].lower()}-r{document['revision']}.pdf",
            )
        except Exception as exc:
            metadata["dispatch_error"] = str(exc)[:2000]
            metadata["ambiguous_provider_create"] = True
            with transaction() as conn:
                update_document(conn, document_id, status="FAILED", metadata=metadata)
                update_job_fields(conn, job_id, last_error=str(exc)[:4000])
            raise PermanentEventError(
                "Documenso dispatch failed after the create boundary. Check Documenso before retrying."
            ) from exc

        envelope_id = str(result.get("id") or "")
        if not envelope_id:
            raise PermanentEventError("Documenso result did not include envelope id")
        metadata["dispatch_completed_at"] = datetime.now(UTC).isoformat()
        metadata["documenso_status"] = result.get("status")
        with transaction() as conn:
            update_document(
                conn,
                document_id,
                status="PENDING",
                documenso_envelope_id=envelope_id,
                documenso_item_ids=result.get("item_ids") or [],
                signing_url=result.get("signing_url"),
                metadata=metadata,
            )
            save_mapping(conn, "documenso", "envelope", document_id, envelope_id)
            current = get_job(conn, job_id)
            if document["kind"] == "WORK_AUTHORIZATION" and current["state"] == WorkflowState.ESTIMATE_SYNCED.value:
                transition_job(conn, job_id, WorkflowState.AUTHORIZATION_SENT)
            audit(
                conn,
                current["organization_id"],
                "SYSTEM",
                None,
                "DOCUMENT_SENT",
                "workflow_document",
                document_id,
                {"kind": document["kind"], "envelope_id": envelope_id},
            )

    def finalize_document(self, job_id: str, payload: dict[str, Any]) -> None:
        document_id = str(payload.get("document_id") or "")
        if not document_id:
            raise PermanentEventError("FINALIZE_DOCUMENT event is missing document_id")
        with transaction() as conn:
            document = get_document(conn, document_id)
            job = get_job(conn, job_id)
        if document["status"] == "COMPLETED":
            return
        if document["status"] != "PENDING":
            raise PermanentEventError(
                f"Document {document_id} cannot be finalized while status is {document['status']}"
            )
        envelope_id = document.get("documenso_envelope_id")
        if not envelope_id:
            raise PermanentEventError("Document has no Documenso envelope id")

        envelope = self.documenso.get_envelope(str(envelope_id))
        summary = self.documenso.summarize(envelope)
        if summary["status"] not in {"COMPLETED", "SIGNED", "EXECUTED"}:
            raise RuntimeError(f"Documenso envelope is not complete yet: {summary['status']}")
        item_ids = list(document.get("documenso_item_ids") or summary.get("item_ids") or [])
        if not item_ids:
            raise PermanentEventError("Completed Documenso envelope does not expose a downloadable item")
        signed_pdf = self.documenso.download_item(str(item_ids[0]))
        stored_path, signed_hash = self.storage.store(
            job_id=job_id,
            kind=document["kind"],
            revision=int(document["revision"]),
            body=signed_pdf,
            signed=True,
        )
        metadata = dict(document.get("metadata") or {})
        metadata["finalized_at"] = datetime.now(UTC).isoformat()
        metadata["documenso_final_status"] = summary["status"]

        if document["kind"] == "WORK_AUTHORIZATION":
            if not job.get("gauzy_estimate_id"):
                raise PermanentEventError("Work Authorization completed before Gauzy estimate was mapped")
            promoted = self.gauzy.promote_estimate_to_invoice(
                str(job["gauzy_estimate_id"]),
                note=f"Work Authorization signed. Archived SHA-256: {signed_hash}",
            )
            gauzy_invoice_id = str(promoted.get("id") or job["gauzy_estimate_id"])
        else:
            gauzy_invoice_id = str(job.get("gauzy_invoice_id") or "")

        with transaction() as conn:
            update_document(
                conn,
                document_id,
                status="COMPLETED",
                signed_pdf_sha256=signed_hash,
                stored_path=stored_path,
                completed_at=datetime.now(UTC),
                documenso_item_ids=item_ids,
                metadata=metadata,
            )
            current = get_job(conn, job_id)
            if document["kind"] == "WORK_AUTHORIZATION":
                update_job_fields(conn, job_id, gauzy_invoice_id=gauzy_invoice_id)
                save_mapping(conn, "gauzy", "invoice", job_id, gauzy_invoice_id)
                if current["state"] == WorkflowState.AUTHORIZATION_SENT.value:
                    transition_job(conn, job_id, WorkflowState.AUTHORIZATION_SIGNED)
                enqueue(conn, job_id, "CREATE_SQUARE_INVOICE")
            elif document["kind"] == "CHANGE_ORDER":
                enqueue(conn, job_id, "CREATE_CHANGE_ORDER_INVOICE", {"document_id": document_id})
            elif document["kind"] == "COMPLETION_OF_SERVICE":
                if current["state"] == WorkflowState.COMPLETION_SENT.value:
                    transition_job(conn, job_id, WorkflowState.COMPLETION_SIGNED)
                enqueue(conn, job_id, "CREATE_FINAL_INVOICE", {"document_id": document_id})
            audit(
                conn,
                current["organization_id"],
                "DOCUMENSO",
                envelope_id,
                "DOCUMENT_COMPLETED",
                "workflow_document",
                document_id,
                {"kind": document["kind"], "sha256": signed_hash},
            )

    def create_square_invoice(self, job_id: str, payload: dict[str, Any]) -> None:
        with transaction() as conn:
            job = get_job(conn, job_id)
        if job.get("square_invoice_id") or (
            self.settings.square_split_final_invoice and job.get("square_customer_id")
            and job["state"] in {WorkflowState.DEPOSIT_PUBLISHED.value, WorkflowState.DEPOSIT_PAID.value, WorkflowState.IN_PROGRESS.value}
        ):
            return
        if job["state"] != WorkflowState.AUTHORIZATION_SIGNED.value:
            raise PermanentEventError(f"Square invoice cannot be created while job is {job['state']}")
        customer = self.square.ensure_customer(job["customer"], job_id)
        customer_id = str(customer.get("id") or "")
        if not customer_id:
            raise RuntimeError("Square customer response did not include id")

        if self.settings.square_split_final_invoice:
            if int(job["deposit_cents"]) > 0:
                result = self.square.create_deposit_invoice(job, customer_id)
                order = result["order"]
                invoice = result["invoice"]
                summary = self.square.summarize_invoice(invoice)
                fields = {
                    "square_customer_id": customer_id,
                    "square_order_id": str(order["id"]),
                    "square_invoice_id": summary["invoice_id"],
                    "square_invoice_version": summary["version"],
                    "square_public_url": summary["public_url"],
                    "square_invoice_role": "DEPOSIT",
                }
            else:
                summary = {"invoice_id": None, "version": None, "public_url": None}
                fields = {"square_customer_id": customer_id, "square_invoice_role": "DEPOSIT"}
        else:
            order = self.square.create_order(job, customer_id)
            invoice = self.square.create_and_publish_invoice(job, customer_id, str(order["id"]))
            summary = self.square.summarize_invoice(invoice)
            fields = {
                "square_customer_id": customer_id,
                "square_order_id": str(order["id"]),
                "square_invoice_id": summary["invoice_id"],
                "square_invoice_version": summary["version"],
                "square_public_url": summary["public_url"],
                "square_invoice_role": "LEGACY",
            }

        with transaction() as conn:
            current = get_job(conn, job_id, for_update=True)
            if current.get("square_invoice_id"):
                return
            update_job_fields(conn, job_id, **fields)
            save_mapping(conn, "square", "customer", job_id, customer_id)
            if fields.get("square_order_id"):
                save_mapping(conn, "square", "order", job_id, str(fields["square_order_id"]), {"role": fields["square_invoice_role"]})
            if fields.get("square_invoice_id"):
                save_mapping(
                    conn, "square", "invoice", job_id, str(fields["square_invoice_id"]),
                    {"role": fields["square_invoice_role"], "amount_cents": int(current["deposit_cents"]) if fields["square_invoice_role"] == "DEPOSIT" else int(current["total_cents"])}
                )
            transition_job(conn, job_id, WorkflowState.DEPOSIT_PUBLISHED)
            if int(current["deposit_cents"]) == 0:
                transition_job(conn, job_id, WorkflowState.DEPOSIT_PAID)
            audit(
                conn, current["organization_id"], "SYSTEM", None, "SQUARE_DEPOSIT_PUBLISHED",
                "workflow_job", job_id, {"square_invoice_id": fields.get("square_invoice_id"), "split_final_invoice": self.settings.square_split_final_invoice},
            )

    def create_change_order_invoice(self, job_id: str, payload: dict[str, Any]) -> None:
        document_id = str(payload.get("document_id") or "")
        if not document_id:
            raise PermanentEventError("CREATE_CHANGE_ORDER_INVOICE event is missing document_id")
        with transaction() as conn:
            document = get_document(conn, document_id)
            job = get_job(conn, job_id)
            existing = get_mapping(conn, "square", "change_order_invoice", job_id + ":" + document_id)
        if existing:
            return
        if document["status"] != "COMPLETED":
            raise RuntimeError("Change Order is not completed")
        metadata = dict(document.get("metadata") or {})
        delta = int(metadata.get("delta_cents", 0))
        revised_total = int(metadata.get("revised_total_cents", job["total_cents"] + delta))
        if revised_total < int(job["deposit_cents"]):
            with transaction() as conn:
                transition_job(conn, job_id, WorkflowState.PAYMENT_REVIEW, error="Revised total is below deposit already requested")
            raise PermanentEventError("Change Order reduces total below the deposit and requires manager review")
        if not job.get("gauzy_invoice_id"):
            raise PermanentEventError("Change Order cannot update an unmapped Gauzy invoice")

        if delta <= 0:
            self.gauzy.update_invoice_total(
                str(job["gauzy_invoice_id"]),
                total_cents=revised_total,
                note=f"Signed Change Order #{document['revision']}; revised contract total recorded.",
            )
            with transaction() as conn:
                update_job_fields(conn, job_id, total_cents=revised_total)
                transition_job(
                    conn,
                    job_id,
                    WorkflowState.PAYMENT_REVIEW if delta < 0 else WorkflowState.IN_PROGRESS,
                    error="Signed negative Change Order requires a manual Square adjustment/refund" if delta < 0 else None,
                )
                save_mapping(
                    conn,
                    "square",
                    "change_order_invoice",
                    job_id + ":" + document_id,
                    f"MANUAL:{document_id}",
                    {"delta_cents": delta, "revised_total_cents": revised_total},
                )
            return

        if not job.get("square_customer_id"):
            raise PermanentEventError("Change Order cannot be billed before Square customer mapping exists")
        # Square creation is protected by its provider idempotency keys. Create it first,
        # then update the Gauzy ledger, so an application retry cannot duplicate line items.
        result = self.square.create_change_order_invoice(job, document, str(job["square_customer_id"]))
        invoice = result["invoice"]
        self.gauzy.update_invoice_total(
            str(job["gauzy_invoice_id"]),
            total_cents=revised_total,
            note=f"Signed Change Order #{document['revision']}; revised contract total recorded.",
        )
        with transaction() as conn:
            update_job_fields(conn, job_id, total_cents=revised_total)
            save_mapping(
                conn,
                "square",
                "change_order_invoice",
                job_id + ":" + document_id,
                str(invoice["id"]),
                {
                    "document_id": document_id,
                    "order_id": result["order"]["id"],
                    "public_url": invoice.get("public_url"),
                    "delta_cents": delta,
                    "revised_total_cents": revised_total,
                },
            )
            current = get_job(conn, job_id)
            if current["state"] == WorkflowState.CHANGE_ORDER_PENDING.value:
                transition_job(conn, job_id, WorkflowState.IN_PROGRESS)
            audit(
                conn,
                current["organization_id"],
                "SYSTEM",
                None,
                "CHANGE_ORDER_BILLED",
                "workflow_document",
                document_id,
                {"square_invoice_id": invoice["id"], "delta_cents": delta},
            )

    def create_final_invoice(self, job_id: str, payload: dict[str, Any]) -> None:
        with transaction() as conn:
            job = get_job(conn, job_id)
            completion = latest_document(conn, job_id, "COMPLETION_OF_SERVICE")
            missing_change_orders = positive_change_orders_missing_invoice(conn, job_id)
            positive_change_total = signed_positive_change_order_cents(conn, job_id)
            paid_before = total_paid_cents(conn, job_id)
        if not completion or completion["status"] != "COMPLETED":
            raise PermanentEventError("Final invoice cannot be issued before Completion of Service is signed")
        if missing_change_orders:
            raise PermanentEventError("Final invoice is blocked until every signed positive Change Order has a Square invoice")
        if job.get("final_invoice_issued_at"):
            return
        if not job.get("gauzy_invoice_id"):
            raise PermanentEventError("Final invoice cannot be issued before Gauzy invoice mapping exists")

        issued_at = datetime.now(UTC)
        due_at = issued_at  # Floodman terms: due the instant the invoice is issued.
        completed_on = str((completion.get("metadata") or {}).get("completed_on") or issued_at.date().isoformat())
        final_result: dict[str, Any] | None = None
        if self.settings.square_split_final_invoice:
            if not job.get("square_customer_id"):
                customer = self.square.ensure_customer(job["customer"], job_id)
                customer_id = str(customer.get("id") or "")
                if not customer_id:
                    raise RuntimeError("Square customer response did not include id")
            else:
                customer_id = str(job["square_customer_id"])
            deposit_paid = 0
            with transaction() as conn:
                deposit_paid = recorded_invoice_paid_cents(conn, job_id, str(job.get("square_invoice_id") or "")) if job.get("square_invoice_id") else 0
            base_contract_cents = max(0, int(job["total_cents"]) - int(positive_change_total))
            final_amount_cents = max(0, base_contract_cents - deposit_paid)
            if final_amount_cents > 0:
                final_result = self.square.create_final_invoice(
                    job, customer_id, amount_cents=final_amount_cents, completed_on=completed_on
                )
        else:
            final_amount_cents = max(0, int(job["total_cents"]) - paid_before)

        self.gauzy.issue_final_invoice(
            str(job["gauzy_invoice_id"]),
            due_date=issued_at.date().isoformat(),
            note=(
                "Final invoice issued after signed Completion of Service. Payment terms: due upon receipt. "
                f"Issued and due at {issued_at.isoformat()}."
            ),
        )

        with transaction() as conn:
            current = get_job(conn, job_id, for_update=True)
            if current.get("final_invoice_issued_at"):
                return
            updates: dict[str, Any] = {
                "final_invoice_issued_at": issued_at,
                "final_invoice_due_at": due_at,
            }
            if final_result and not final_result.get("skipped"):
                invoice = final_result["invoice"]
                summary = self.square.summarize_invoice(invoice)
                updates.update(
                    square_final_order_id=str(final_result["order"]["id"]),
                    square_final_invoice_id=summary["invoice_id"],
                    square_final_invoice_version=summary["version"],
                    square_final_public_url=summary["public_url"],
                )
                save_mapping(
                    conn, "square", "final_invoice", job_id, summary["invoice_id"],
                    {"order_id": str(final_result["order"]["id"]), "public_url": summary["public_url"], "amount_cents": int(final_result["amount_cents"]), "due_at": due_at.isoformat()}
                )
            update_job_fields(conn, job_id, **updates)
            current = get_job(conn, job_id)
            paid_now = total_paid_cents(conn, job_id)
            balance = max(0, int(current["total_cents"]) - paid_now)
            phone = normalize_e164(str(current["customer"].get("phone") or ""), default_country="US")
            consent_status = str(current["customer"].get("sms_consent") or "UNKNOWN")
            if phone:
                captured_raw = current["customer"].get("sms_consent_captured_at")
                captured = datetime.fromisoformat(str(captured_raw).replace("Z", "+00:00")) if captured_raw else None
                upsert_sms_consent(
                    conn, organization_id=str(current["organization_id"]), job_id=job_id, phone_e164=phone,
                    status=consent_status, source=str(current["customer"].get("sms_consent_source") or "ROOMFLOW"),
                    disclosure_version=current["customer"].get("sms_consent_disclosure_version"),
                    captured_at=captured,
                    evidence={
                        "roomflow_job_id": current["roomflow_job_id"],
                        "disclosure_text": current["customer"].get("sms_consent_disclosure_text"),
                        "evidence_id": current["customer"].get("sms_consent_evidence_id"),
                    },
                )
            case = upsert_ar_case(
                conn, job=current, issued_at=issued_at, due_at=due_at, balance_cents=balance,
                recipient_phone_e164=phone, customer_timezone=str(current["customer"].get("timezone") or self.settings.ar_timezone),
                next_reminder_at=first_reminder_at(issued_at, self.settings.ar_reminder_offsets_hours) if balance > 0 else None,
                stage="FINAL", metadata={"due_upon_receipt": True, "square_calendar_due_date": issued_at.date().isoformat()},
            )
            if balance <= 0:
                if current["state"] not in {WorkflowState.PAID.value, WorkflowState.CLOSED.value}:
                    transition_job(conn, job_id, WorkflowState.PAID)
                latest = get_job(conn, job_id)
                if latest["state"] == WorkflowState.PAID.value:
                    transition_job(conn, job_id, WorkflowState.CLOSED)
            elif current["state"] == WorkflowState.COMPLETION_SIGNED.value:
                transition_job(conn, job_id, WorkflowState.FINAL_PAYMENT_DUE)
            enqueue(conn, job_id, "SEND_INITIAL_INVOICE", {"ar_case_id": str(case["id"])})
            alert = create_staff_alert(
                conn, organization_id=str(current["organization_id"]), job_id=job_id, ar_case_id=str(case["id"]), thread_id=None,
                alert_type="FINAL_INVOICE_ISSUED", severity="INFO", title=f"Final invoice F-{current['invoice_number']}-FINAL issued",
                body=f"Invoice is due upon receipt. Current balance: {balance} cents.", metadata={"due_at": due_at.isoformat(), "balance_cents": balance},
            )
            enqueue(conn, job_id, "SEND_STAFF_ALERT", {"alert_id": str(alert["id"])})
            audit(conn, str(current["organization_id"]), "SYSTEM", None, "FINAL_INVOICE_ISSUED", "workflow_job", job_id, {"issued_at": issued_at.isoformat(), "due_at": due_at.isoformat(), "balance_cents": balance})

    def send_initial_invoice(self, job_id: str, payload: dict[str, Any]) -> None:
        try:
            self.receivables.send_initial_invoice(job_id)
        except AmbiguousDeliveryError as exc:
            raise PermanentEventError(str(exc)) from exc

    def send_ar_reminder(self, job_id: str, payload: dict[str, Any]) -> None:
        # Always reconcile Square immediately before speaking about a balance.
        self.reconcile_job_payments(job_id, {"reason": "pre_reminder_reconciliation"})
        try:
            self.receivables.send_past_due_reminder(
                job_id,
                expected_case_id=str(payload.get("ar_case_id") or "") or None,
                expected_reminder_count=(
                    int(payload["reminder_count"]) if payload.get("reminder_count") is not None else None
                ),
            )
        except AmbiguousDeliveryError as exc:
            raise PermanentEventError(str(exc)) from exc

    def process_inbound_message(self, job_id: str, payload: dict[str, Any]) -> None:
        try:
            self.receivables.process_inbound_message(job_id, payload)
        except AmbiguousDeliveryError as exc:
            raise PermanentEventError(str(exc)) from exc

    def send_staff_alert(self, job_id: str, payload: dict[str, Any]) -> None:
        alert_id = str(payload.get("alert_id") or "")
        if not alert_id:
            raise PermanentEventError("SEND_STAFF_ALERT requires alert_id")
        try:
            self.receivables.send_staff_alert(alert_id)
        except AmbiguousDeliveryError as exc:
            raise PermanentEventError(str(exc)) from exc

    def send_payment_confirmation(self, job_id: str, payload: dict[str, Any]) -> None:
        try:
            self.receivables.send_payment_confirmation(job_id, int(payload.get("paid_delta_cents") or 0))
        except AmbiguousDeliveryError as exc:
            raise PermanentEventError(str(exc)) from exc

    def send_help_reply(self, job_id: str, payload: dict[str, Any]) -> None:
        message_id = str(payload.get("message_id") or "")
        if not message_id:
            raise PermanentEventError("SEND_HELP_REPLY requires message_id")
        try:
            self.receivables.send_help_reply(job_id, message_id)
        except AmbiguousDeliveryError as exc:
            raise PermanentEventError(str(exc)) from exc

    def send_manual_reply(self, job_id: str, payload: dict[str, Any]) -> None:
        thread_id = str(payload.get("thread_id") or "")
        body = str(payload.get("body") or "").strip()
        actor = str(payload.get("actor") or "STAFF")
        if not thread_id or not body:
            raise PermanentEventError("SEND_MANUAL_REPLY requires thread_id and body")
        try:
            self.receivables.send_manual_reply(thread_id=thread_id, body=body, actor=actor)
        except AmbiguousDeliveryError as exc:
            raise PermanentEventError(str(exc)) from exc

    def process_square_event(self, job_id: str, payload: dict[str, Any]) -> None:
        invoice_id = str(payload.get("invoice_id") or "")
        if not invoice_id:
            raise PermanentEventError("PROCESS_SQUARE_EVENT event is missing invoice_id")
        invoice = self.square.get_invoice(invoice_id)
        summary = self.square.summarize_invoice(invoice)
        now = datetime.now(UTC)
        with transaction() as conn:
            job = get_job(conn, job_id, for_update=True)
            recorded = recorded_invoice_paid_cents(conn, job_id, invoice_id)
            provider_paid = int(summary["paid_cents"])
            if provider_paid < recorded:
                transition_job(
                    conn,
                    job_id,
                    WorkflowState.PAYMENT_REVIEW,
                    error="Square paid amount decreased; refund or dispute reconciliation is required",
                )
                ar_case = get_ar_case_by_job(conn, job_id, for_update=True)
                if ar_case:
                    create_collection_hold(
                        conn,
                        case=ar_case,
                        hold_type="PAYMENT_REVIEW",
                        reason=(
                            "Square reports less paid than Floodman previously recorded. Automated reminders are paused "
                            "until a refund, dispute, or provider correction is reconciled."
                        ),
                        created_by="SQUARE_RECONCILIATION",
                        metadata={
                            "provider_invoice_id": invoice_id,
                            "recorded_paid_cents": recorded,
                            "provider_paid_cents": provider_paid,
                            "square_invoice_version": summary["version"],
                        },
                    )
                alert = create_staff_alert(
                    conn,
                    organization_id=str(job["organization_id"]),
                    job_id=job_id,
                    ar_case_id=str(ar_case["id"]) if ar_case else None,
                    thread_id=None,
                    alert_type="SQUARE_PAYMENT_DECREASE",
                    severity="CRITICAL",
                    title=f"Square payment decrease requires review for invoice F-{job['invoice_number']}",
                    body=(
                        f"Square invoice {invoice_id} now reports {provider_paid} paid cents, below the "
                        f"{recorded} cents already recorded. Customer reminders were paused."
                    ),
                    dedupe_key=f"square-payment-decrease:{invoice_id}:{summary['version']}:{provider_paid}",
                    metadata={
                        "provider_invoice_id": invoice_id,
                        "recorded_paid_cents": recorded,
                        "provider_paid_cents": provider_paid,
                        "square_invoice_version": summary["version"],
                    },
                )
                enqueue(conn, job_id, "SEND_STAFF_ALERT", {"alert_id": str(alert["id"])})
                return
            delta = provider_paid - recorded
            if delta:
                synthetic_id = f"invoice:{invoice_id}:v{summary['version']}:paid:{provider_paid}"
                record_payment_delta(
                    conn,
                    job_id=job_id,
                    provider_invoice_id=invoice_id,
                    provider_payment_id=synthetic_id,
                    amount_cents=delta,
                    currency=job["currency"],
                    payment_type="SQUARE_INVOICE",
                    occurred_at=now,
                    payload={"invoice_status": summary["status"], "payment_requests": summary["payment_requests"]},
                )
            if invoice_id == job.get("square_invoice_id"):
                update_job_fields(
                    conn, job_id, square_invoice_version=summary["version"],
                    square_public_url=summary["public_url"] or job.get("square_public_url"),
                )
            elif invoice_id == job.get("square_final_invoice_id"):
                update_job_fields(
                    conn, job_id, square_final_invoice_version=summary["version"],
                    square_final_public_url=summary["public_url"] or job.get("square_final_public_url"),
                )
            aggregate_paid = total_paid_cents(conn, job_id)
            ar_case = sync_ar_case_balance(
                conn, job_id=job_id, balance_cents=max(0, int(job["total_cents"]) - aggregate_paid),
                reopen_reminder_at=datetime.now(UTC),
            )
            if delta and ar_case:
                enqueue(conn, job_id, "SEND_PAYMENT_CONFIRMATION", {"paid_delta_cents": delta, "provider_invoice_id": invoice_id})
            if str(summary["status"]).upper() in {"CANCELED", "FAILED"}:
                review_reason = (
                    f"Square invoice {invoice_id} entered {str(summary['status']).upper()} status. "
                    "Automated reminders are paused until staff confirms the correct invoice and balance."
                )
                transition_job(conn, job_id, WorkflowState.PAYMENT_REVIEW, error=review_reason)
                current_case = get_ar_case_by_job(conn, job_id, for_update=True)
                if current_case and int(current_case["current_balance_cents"]) > 0:
                    create_collection_hold(
                        conn,
                        case=current_case,
                        hold_type="PAYMENT_REVIEW",
                        reason=review_reason,
                        created_by="SQUARE_RECONCILIATION",
                        metadata={
                            "provider_invoice_id": invoice_id,
                            "square_status": str(summary["status"]).upper(),
                            "square_invoice_version": summary["version"],
                        },
                    )
                alert = create_staff_alert(
                    conn,
                    organization_id=str(job["organization_id"]),
                    job_id=job_id,
                    ar_case_id=str(current_case["id"]) if current_case else None,
                    thread_id=None,
                    alert_type="SQUARE_INVOICE_REVIEW",
                    severity="CRITICAL",
                    title=f"Square invoice {str(summary['status']).upper()} for F-{job['invoice_number']}",
                    body=review_reason,
                    dedupe_key=(
                        f"square-invoice-review:{invoice_id}:{summary['version']}:"
                        f"{str(summary['status']).upper()}"
                    ),
                    metadata={
                        "provider_invoice_id": invoice_id,
                        "square_status": str(summary["status"]).upper(),
                        "square_invoice_version": summary["version"],
                    },
                )
                enqueue(conn, job_id, "SEND_STAFF_ALERT", {"alert_id": str(alert["id"])})

        if not job.get("gauzy_invoice_id") or not job.get("gauzy_contact_id"):
            raise PermanentEventError("Square payment cannot be synchronized before Gauzy mappings exist")
        while True:
            with transaction() as conn:
                payment = claim_pending_ledger_payment(conn, job_id)
            if not payment:
                break
            try:
                gauzy_payment = self.gauzy.record_payment(
                    invoice_id=str(job["gauzy_invoice_id"]),
                    contact_id=str(job["gauzy_contact_id"]),
                    amount_cents=int(payment["amount_cents"]),
                    currency=str(payment["currency"]),
                    payment_date=(payment.get("occurred_at") or now).isoformat(),
                    note=f"Square invoice {payment.get('provider_invoice_id')}; reconciled payment ledger",
                    provider_reference=str(payment.get("provider_payment_id") or payment["id"]),
                    project_id=str(job.get("gauzy_project_id") or "") or None,
                )
            except Exception as exc:
                with transaction() as conn:
                    mark_payment_ledger_failed(conn, str(payment["id"]), str(exc))
                raise
            with transaction() as conn:
                mark_payment_ledger_synced(
                    conn, str(payment["id"]), str(gauzy_payment.get("id") or "") or None
                )
        if job.get("gauzy_invoice_id"):
            self.gauzy.update_invoice_payment_status(
                str(job["gauzy_invoice_id"]), paid_cents=aggregate_paid, total_cents=int(job["total_cents"])
            )
        with transaction() as conn:
            refreshed = get_job(conn, job_id)
            main_deposit_paid = (
                recorded_invoice_paid_cents(conn, job_id, str(refreshed.get("square_invoice_id") or ""))
                if refreshed.get("square_invoice_id") and str(refreshed.get("square_invoice_role") or "") == "DEPOSIT"
                else int(summary["deposit_paid_cents"])
            )
        self._apply_payment_state(job_id, aggregate_paid, int(job["total_cents"]), main_deposit_paid)

    def reconcile_job_payments(self, job_id: str, payload: dict[str, Any]) -> None:
        with transaction() as conn:
            job = get_job(conn, job_id)
        invoice_ids: list[str] = []
        if job.get("square_invoice_id"):
            invoice_ids.append(str(job["square_invoice_id"]))
        if job.get("square_final_invoice_id"):
            invoice_ids.append(str(job["square_final_invoice_id"]))
        with transaction() as conn:
            invoice_ids.extend(list_change_order_invoice_ids(conn, job_id))
        if invoice_ids:
            for invoice_id in dict.fromkeys(invoice_ids):
                self.process_square_event(job_id, {"invoice_id": invoice_id, "reason": "reconcile"})
        else:
            with transaction() as conn:
                current = get_job(conn, job_id)
                if current["state"] == WorkflowState.COMPLETION_SIGNED.value:
                    transition_job(conn, job_id, WorkflowState.PAYMENT_REVIEW, error="No Square invoice exists")

    def _apply_payment_state(self, job_id: str, paid_cents: int, total_cents: int, main_deposit_paid: int) -> None:
        with transaction() as conn:
            job = get_job(conn, job_id, for_update=True)
            state = WorkflowState(job["state"])
            completion = latest_document(conn, job_id, "COMPLETION_OF_SERVICE")
            completion_signed = bool(completion and completion["status"] == "COMPLETED")
            if paid_cents > total_cents:
                if state != WorkflowState.PAYMENT_REVIEW:
                    transition_job(
                        conn, job_id, WorkflowState.PAYMENT_REVIEW,
                        error=f"Square reports an overpayment of {paid_cents - total_cents} cents",
                    )
                return
            if paid_cents == total_cents:
                if state not in {WorkflowState.PAID, WorkflowState.CLOSED}:
                    transition_job(conn, job_id, WorkflowState.PAID)
                    state = WorkflowState.PAID
                if completion_signed and state == WorkflowState.PAID:
                    transition_job(conn, job_id, WorkflowState.CLOSED)
                return
            if state == WorkflowState.DEPOSIT_PUBLISHED and main_deposit_paid >= int(job["deposit_cents"]):
                transition_job(conn, job_id, WorkflowState.DEPOSIT_PAID)
                return
            if completion_signed and state == WorkflowState.COMPLETION_SIGNED:
                transition_job(conn, job_id, WorkflowState.FINAL_PAYMENT_DUE)
