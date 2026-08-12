from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from .adapters.email import EmailClient
from .adapters.messaging_ai import MessagingAIClient
from .adapters.twilio import TwilioClient
from .ar import days_past_due, next_reminder, next_send_window, promise_pause_until, within_send_window
from .config import Settings
from .db import transaction
from .message_policy import enforce_ai_decision, immediate_hold_type, requires_immediate_human, validate_promise_date
from .message_templates import (
    help_sms,
    invoice_sent_email,
    invoice_sent_sms,
    money,
    past_due_email,
    past_due_sms,
    payment_received_sms,
    safe_acknowledgement,
    staff_alert_message,
)
from .repository import (
    audit,
    count_recent_outbound_sms,
    create_collection_hold,
    create_payment_promise,
    create_staff_alert,
    ensure_message_thread,
    get_ar_case,
    get_ar_case_by_job,
    get_job,
    get_message_event,
    get_message_thread,
    get_sms_consent,
    get_staff_alert,
    list_thread_messages,
    mark_message_failed,
    mark_message_sending,
    mark_message_sent,
    mark_staff_alert_delivery,
    record_ai_message_decision,
    reserve_outbound_message,
    sync_ar_case_balance,
    total_paid_cents,
    unlock_ar_case,
    update_ar_case,
    update_message_thread,
    upsert_sms_consent,
)
from .security import create_portal_token

logger = logging.getLogger(__name__)


class AmbiguousDeliveryError(RuntimeError):
    """A provider call crossed an ambiguous delivery boundary and needs review."""


class ReceivablesManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.twilio = TwilioClient(settings)
        self.email = EmailClient(settings)
        self.ai = MessagingAIClient(settings)

    def close(self) -> None:
        self.twilio.close()
        self.ai.close()

    def portal_url(self, job: dict[str, Any]) -> str:
        token = create_portal_token(
            str(job["id"]),
            int(job["portal_token_version"]),
            self.settings.portal_token_secret,
            self.settings.portal_token_ttl_seconds,
        )
        return f"{self.settings.portal_base_url}/{token}"

    @staticmethod
    def _business_phone(settings: Settings) -> str | None:
        return settings.twilio_from_number or settings.twilio_messaging_service_sid or None

    def _thread_for_case(self, case: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
        phone = str(case.get("recipient_phone_e164") or "").strip() or None
        email = str(case.get("recipient_email") or "").strip().lower() or None
        with transaction() as conn:
            return ensure_message_thread(
                conn,
                organization_id=str(case["organization_id"]),
                job_id=str(job["id"]),
                ar_case_id=str(case["id"]),
                customer_phone_e164=phone,
                customer_email=email,
                business_phone_e164=self._business_phone(self.settings),
            )

    def _send_email_once(
        self,
        *,
        thread: dict[str, Any],
        job: dict[str, Any],
        case: dict[str, Any],
        message_kind: str,
        dedupe_key: str,
        subject: str,
        text_body: str,
        html_body: str | None,
        recipients: list[str],
    ) -> dict[str, Any] | None:
        if not self.settings.smtp_enabled:
            return None
        with transaction() as conn:
            event, created = reserve_outbound_message(
                conn,
                thread_id=str(thread["id"]),
                job_id=str(job["id"]),
                ar_case_id=str(case["id"]),
                channel="EMAIL",
                provider="smtp",
                message_kind=message_kind,
                body=text_body,
                dedupe_key=dedupe_key,
                metadata={"subject": subject, "recipients": recipients},
            )
            if not created:
                if event["status"] in {"SENT", "DELIVERED"}:
                    return event
                if event["status"] == "SENDING" or (
                    event["status"] == "FAILED"
                    and bool((event.get("metadata") or {}).get("ambiguous_provider_boundary"))
                ):
                    raise AmbiguousDeliveryError(f"Email {dedupe_key} may already have been accepted")
            mark_message_sending(conn, str(event["id"]))
        try:
            provider_id = self.email.send(
                to=recipients,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
            )
        except Exception as exc:
            with transaction() as conn:
                mark_message_failed(
                    conn,
                    message_id=str(event["id"]),
                    error_code="SMTP_DELIVERY_AMBIGUOUS",
                    error_message=str(exc),
                    metadata={"ambiguous_provider_boundary": True},
                )
            raise AmbiguousDeliveryError(str(exc)) from exc
        with transaction() as conn:
            return mark_message_sent(
                conn,
                message_id=str(event["id"]),
                provider_message_id=provider_id,
                status="SENT",
            )

    def _sms_allowed(self, case: dict[str, Any], thread: dict[str, Any]) -> tuple[bool, str]:
        if not self.settings.twilio_enabled:
            return False, "TWILIO_DISABLED"
        phone = str(case.get("recipient_phone_e164") or "")
        if not phone:
            return False, "PHONE_MISSING"
        with transaction() as conn:
            consent = get_sms_consent(conn, str(case["organization_id"]), phone)
            recent = count_recent_outbound_sms(conn, str(thread["id"]), days=7)
        if self.settings.ar_require_sms_consent and (not consent or consent["status"] != "OPTED_IN"):
            return False, "SMS_CONSENT_REQUIRED"
        if recent >= self.settings.ar_max_sms_per_seven_days:
            return False, "SMS_RATE_LIMIT"
        return True, "ALLOWED"

    def _send_sms_once(
        self,
        *,
        thread: dict[str, Any],
        job: dict[str, Any],
        case: dict[str, Any],
        message_kind: str,
        dedupe_key: str,
        body: str,
        bypass_rate_limit: bool = False,
        bypass_consent: bool = False,
    ) -> dict[str, Any] | None:
        allowed, reason = self._sms_allowed(case, thread)
        if bypass_rate_limit and reason == "SMS_RATE_LIMIT":
            allowed = True
        if bypass_consent and reason in {"SMS_CONSENT_REQUIRED"}:
            allowed = True
        with transaction() as conn:
            event, created = reserve_outbound_message(
                conn,
                thread_id=str(thread["id"]),
                job_id=str(job["id"]),
                ar_case_id=str(case["id"]),
                channel="SMS",
                provider="twilio",
                message_kind=message_kind,
                body=body,
                dedupe_key=dedupe_key,
                metadata={"recipient": case.get("recipient_phone_e164"), "policy": reason},
            )
            if not allowed:
                if created or event["status"] not in {"SENT", "DELIVERED"}:
                    mark_message_failed(
                        conn,
                        message_id=str(event["id"]),
                        error_code=reason,
                        error_message="SMS suppressed by Floodman communication policy",
                        suppress=True,
                    )
                return event
            if not created:
                if event["status"] in {"SENT", "DELIVERED"}:
                    return event
                if event["status"] == "SENDING" or (event["status"] == "FAILED" and bool((event.get("metadata") or {}).get("ambiguous_provider_boundary"))):
                    raise AmbiguousDeliveryError(f"SMS {dedupe_key} may already have been accepted")
            mark_message_sending(conn, str(event["id"]))
        try:
            result = self.twilio.send_sms(to=str(case["recipient_phone_e164"]), body=body)
        except Exception as exc:
            with transaction() as conn:
                mark_message_failed(
                    conn,
                    message_id=str(event["id"]),
                    error_code="TWILIO_DELIVERY_AMBIGUOUS",
                    error_message=str(exc),
                    metadata={"ambiguous_provider_boundary": True},
                )
            raise AmbiguousDeliveryError(str(exc)) from exc
        with transaction() as conn:
            return mark_message_sent(
                conn,
                message_id=str(event["id"]),
                provider_message_id=str(result["sid"]),
                status=str(result.get("status") or "queued").upper() if str(result.get("status") or "").upper() in {"SENT", "DELIVERED"} else "SENT",
                metadata={"twilio_status": result.get("status")},
            )

    def send_initial_invoice(self, job_id: str) -> None:
        with transaction() as conn:
            job = get_job(conn, job_id)
            case = get_ar_case_by_job(conn, job_id)
        if not case or int(case["current_balance_cents"]) <= 0:
            return
        thread = self._thread_for_case(case, job)
        portal = self.portal_url(job)
        payment_url = job.get("square_final_public_url") or job.get("square_public_url")
        rendered = invoice_sent_email(
            customer_name=str(case["customer_name"]),
            invoice_number=str(case["invoice_number"]),
            balance_cents=int(case["current_balance_cents"]),
            portal_url=portal,
            payment_url=str(payment_url) if payment_url else None,
        )
        self._send_email_once(
            thread=thread,
            job=job,
            case=case,
            message_kind="INVOICE_SENT",
            dedupe_key=f"invoice-sent-email:{job_id}:{case['issued_at'].isoformat()}",
            subject=rendered.subject,
            text_body=rendered.text,
            html_body=rendered.html,
            recipients=[str(case["recipient_email"])],
        )
        if case.get("recipient_phone_e164"):
            self._send_sms_once(
                thread=thread,
                job=job,
                case=case,
                message_kind="INVOICE_SENT",
                dedupe_key=f"invoice-sent-sms:{job_id}:{case['issued_at'].isoformat()}",
                body=invoice_sent_sms(
                    invoice_number=str(case["invoice_number"]),
                    balance_cents=int(case["current_balance_cents"]),
                    portal_url=portal,
                ),
                bypass_rate_limit=True,
            )
        with transaction() as conn:
            audit(
                conn,
                str(job["organization_id"]),
                "SYSTEM",
                None,
                "FINAL_INVOICE_DELIVERED",
                "ar_case",
                str(case["id"]),
                {"due_at": case["due_at"].isoformat(), "balance_cents": int(case["current_balance_cents"])},
            )

    def send_past_due_reminder(
        self,
        job_id: str,
        *,
        expected_case_id: str | None = None,
        expected_reminder_count: int | None = None,
    ) -> None:
        now = datetime.now(UTC)
        with transaction() as conn:
            job = get_job(conn, job_id)
            case = get_ar_case_by_job(conn, job_id, for_update=True)
            if not case:
                return
            if expected_case_id and str(case["id"]) != expected_case_id:
                unlock_ar_case(conn, str(case["id"]))
                return
            if expected_reminder_count is not None and int(case["reminder_count"]) != expected_reminder_count:
                # A newer reminder already advanced the case. This outbox event is stale.
                unlock_ar_case(conn, str(case["id"]))
                return
            if int(case["current_balance_cents"]) <= 0 or case["status"] in {"PAID", "CLOSED", "HOLD", "DISPUTED", "PROMISE_TO_PAY"}:
                unlock_ar_case(conn, str(case["id"]))
                return
            if case.get("paused_until") and case["paused_until"] > now:
                unlock_ar_case(conn, str(case["id"]), next_reminder_at=case["paused_until"])
                return
            if self.settings.ar_max_automated_age_days:
                age = days_past_due(now, case["due_at"], str(case["customer_timezone"]))
                if age > self.settings.ar_max_automated_age_days:
                    update_ar_case(
                        conn,
                        str(case["id"]),
                        status="HOLD",
                        next_reminder_at=None,
                        hold_reason="Maximum automated reminder age reached",
                        locked_at=None,
                        locked_by=None,
                    )
                    return
            if not within_send_window(
                now,
                str(case["customer_timezone"]),
                self.settings.ar_send_start_local,
                self.settings.ar_send_end_local,
            ):
                target = next_send_window(
                    now,
                    str(case["customer_timezone"]),
                    self.settings.ar_send_start_local,
                    self.settings.ar_send_end_local,
                )
                unlock_ar_case(conn, str(case["id"]), next_reminder_at=target)
                return
        thread = self._thread_for_case(case, job)
        portal = self.portal_url(job)
        age_days = days_past_due(now, case["due_at"], str(case["customer_timezone"]))
        sequence = int(case["reminder_count"]) + 1
        rendered = past_due_email(
            customer_name=str(case["customer_name"]),
            invoice_number=str(case["invoice_number"]),
            balance_cents=int(case["current_balance_cents"]),
            days_overdue=age_days,
            portal_url=portal,
        )
        self._send_email_once(
            thread=thread,
            job=job,
            case=case,
            message_kind="PAST_DUE_REMINDER",
            dedupe_key=f"past-due-email:{case['id']}:{sequence}",
            subject=rendered.subject,
            text_body=rendered.text,
            html_body=rendered.html,
            recipients=[str(case["recipient_email"])],
        )
        if case.get("recipient_phone_e164"):
            self._send_sms_once(
                thread=thread,
                job=job,
                case=case,
                message_kind="PAST_DUE_REMINDER",
                dedupe_key=f"past-due-sms:{case['id']}:{sequence}",
                body=past_due_sms(
                    invoice_number=str(case["invoice_number"]),
                    balance_cents=int(case["current_balance_cents"]),
                    days_overdue=age_days,
                    portal_url=portal,
                ),
            )
        advance = next_reminder(
            issued_at=case["issued_at"],
            current_index=int(case["reminder_index"]),
            repeat_count=int(case["repeat_count"]),
            offsets_hours=self.settings.ar_reminder_offsets_hours,
            repeat_interval_hours=self.settings.ar_repeat_interval_hours,
        )
        with transaction() as conn:
            update_ar_case(
                conn,
                str(case["id"]),
                reminder_index=advance.reminder_index,
                repeat_count=advance.repeat_count,
                reminder_count=sequence,
                last_reminder_at=now,
                next_reminder_at=advance.next_reminder_at,
                locked_at=None,
                locked_by=None,
            )
            audit(
                conn,
                str(job["organization_id"]),
                "SYSTEM",
                None,
                "PAST_DUE_REMINDER_SENT",
                "ar_case",
                str(case["id"]),
                {"sequence": sequence, "days_past_due": age_days, "balance_cents": int(case["current_balance_cents"])},
            )
            if age_days in {7, 14, 21, 30} or (age_days > 30 and sequence % 2 == 0):
                alert = create_staff_alert(
                    conn,
                    organization_id=str(job["organization_id"]),
                    job_id=job_id,
                    ar_case_id=str(case["id"]),
                    thread_id=str(thread["id"]) if thread else None,
                    alert_type="PAST_DUE_THRESHOLD",
                    severity="CRITICAL" if age_days >= 30 else "WARNING",
                    title=f"Invoice {case['invoice_number']} is {age_days} days past due",
                    body=f"Current balance: {money(int(case['current_balance_cents']))}. Reminder sequence {sequence} was sent.",
                    dedupe_key=f"past-due-threshold:{case['id']}:{age_days}:{sequence}",
                    metadata={"days_past_due": age_days, "balance_cents": int(case["current_balance_cents"])},
                )
                from .repository import enqueue

                enqueue(conn, job_id, "SEND_STAFF_ALERT", {"alert_id": str(alert["id"])})

    def send_payment_confirmation(self, job_id: str, paid_delta_cents: int) -> None:
        if paid_delta_cents <= 0:
            return
        with transaction() as conn:
            job = get_job(conn, job_id)
            case = get_ar_case_by_job(conn, job_id)
        if not case:
            return
        thread = self._thread_for_case(case, job)
        if not case.get("recipient_phone_e164"):
            return
        self._send_sms_once(
            thread=thread,
            job=job,
            case=case,
            message_kind="PAYMENT_RECEIVED",
            dedupe_key=f"payment-received:{job_id}:{total_paid_cents_value(job_id=self._job_id(job), paid_delta=paid_delta_cents, case=case)}",
            body=payment_received_sms(
                invoice_number=str(case["invoice_number"]),
                paid_cents=paid_delta_cents,
                remaining_cents=int(case["current_balance_cents"]),
                portal_url=self.portal_url(job),
            ),
            bypass_rate_limit=True,
        )

    @staticmethod
    def _job_id(job: dict[str, Any]) -> str:
        return str(job["id"])

    def send_staff_alert(self, alert_id: str) -> None:
        with transaction() as conn:
            alert = get_staff_alert(conn, alert_id)
            if (alert.get("metadata") or {}).get("delivery_status") == "DELIVERED":
                return
            job = get_job(conn, str(alert["job_id"])) if alert.get("job_id") else None
        job_id = str(alert.get("job_id") or "not linked")
        rendered = staff_alert_message(
            title=str(alert["title"]),
            body=str(alert["body"]),
            job_id=job_id,
            invoice_number=(str((job or {}).get("invoice_number")) if job else None),
        )
        try:
            if self.settings.smtp_enabled and self.settings.ar_staff_emails:
                self.email.send(
                    to=list(self.settings.ar_staff_emails),
                    subject=rendered.subject,
                    text_body=rendered.text,
                    html_body=rendered.html,
                )
            if self.settings.ar_staff_sms_enabled and self.settings.twilio_enabled:
                for number in self.settings.ar_staff_sms_numbers:
                    self.twilio.send_sms(to=number, body=f"Floodman alert: {alert['title']} | {alert['body'][:900]}")
        except Exception as exc:
            with transaction() as conn:
                mark_staff_alert_delivery(conn, alert_id, delivered=False, error=str(exc), metadata={"ambiguous_provider_boundary": True})
            raise AmbiguousDeliveryError(str(exc)) from exc
        with transaction() as conn:
            mark_staff_alert_delivery(
                conn, alert_id, delivered=True,
                metadata={"email_recipients": len(self.settings.ar_staff_emails), "staff_sms_recipients": len(self.settings.ar_staff_sms_numbers) if self.settings.ar_staff_sms_enabled else 0},
            )
            if job:
                audit(
                    conn, str(job["organization_id"]), "SYSTEM", None, "STAFF_ALERT_DELIVERED",
                    "staff_alert", alert_id, {"email_recipients": len(self.settings.ar_staff_emails)},
                )

    def _pause_and_alert(
        self,
        *,
        job: dict[str, Any],
        case: dict[str, Any],
        thread: dict[str, Any],
        inbound: dict[str, Any],
        hold_type: str,
        reason: str,
        severity: str = "WARNING",
    ) -> str:
        with transaction() as conn:
            current_case = get_ar_case(conn, str(case["id"]), for_update=True)
            create_collection_hold(
                conn,
                case=current_case,
                hold_type=hold_type,
                reason=reason,
                created_by="AI_MESSAGE_POLICY",
                metadata={"inbound_message_id": str(inbound["id"])},
            )
            update_message_thread(conn, str(thread["id"]), status="HUMAN_REQUIRED")
            alert = create_staff_alert(
                conn,
                organization_id=str(job["organization_id"]),
                job_id=str(job["id"]),
                ar_case_id=str(case["id"]),
                thread_id=str(thread["id"]),
                alert_type="CUSTOMER_MESSAGE_ESCALATION",
                severity=severity,
                title=f"Customer reply needs review for invoice {case['invoice_number']}",
                body=f"{reason}\n\nCustomer message: {inbound['body']}",
                dedupe_key=f"customer-message:{inbound['id']}:{hold_type}",
                metadata={"message_id": str(inbound["id"]), "hold_type": hold_type},
            )
            from .repository import enqueue

            enqueue(conn, str(job["id"]), "SEND_STAFF_ALERT", {"alert_id": str(alert["id"])})
        return safe_acknowledgement()

    def process_inbound_message(self, job_id: str, payload: dict[str, Any]) -> None:
        message_id = str(payload.get("message_id") or "")
        if not message_id:
            raise ValueError("PROCESS_INBOUND_MESSAGE requires message_id")
        with transaction() as conn:
            inbound = get_message_event(conn, message_id)
            thread = get_message_thread(conn, str(inbound["thread_id"]))
            job = get_job(conn, job_id)
            case = get_ar_case_by_job(conn, job_id)
            history = list(reversed(list_thread_messages(conn, str(thread["id"]), limit=12)))
        if not case:
            return
        body = str(inbound.get("body") or "")
        if not self.settings.messaging_ai_enabled:
            reply = self._pause_and_alert(
                job=job,
                case=case,
                thread=thread,
                inbound=inbound,
                hold_type="MANUAL",
                reason="AI-assisted message triage is disabled; customer reply requires staff review.",
                severity="INFO",
            )
            self._send_sms_once(
                thread=thread,
                job=job,
                case=case,
                message_kind="MANUAL_REVIEW_ACK",
                dedupe_key=f"manual-review-ack:{message_id}",
                body=reply,
                bypass_rate_limit=True,
            )
            return
        multiple_open_case_ids = [str(value) for value in payload.get("multiple_open_case_ids") or [] if value]
        if len(multiple_open_case_ids) > 1:
            reply = self._pause_and_alert(
                job=job,
                case=case,
                thread=thread,
                inbound=inbound,
                hold_type="MANUAL",
                reason=(
                    "This phone number is linked to more than one unpaid Floodman invoice, and the message "
                    "did not contain one exact invoice number. Automated reminders were paused for staff review."
                ),
                severity="WARNING",
            )
            self._send_sms_once(
                thread=thread,
                job=job,
                case=case,
                message_kind="AMBIGUOUS_ACCOUNT_ACK",
                dedupe_key=f"ambiguous-account-ack:{message_id}",
                body=(
                    "Floodman: We found more than one open invoice for this phone number. Automated reminders "
                    "are paused while our office reviews your message. Reply with the exact invoice number or call the office."
                ),
                bypass_rate_limit=True,
            )
            return
        if requires_immediate_human(body):
            hold_type = immediate_hold_type(body)
            reply = self._pause_and_alert(
                job=job,
                case=case,
                thread=thread,
                inbound=inbound,
                hold_type=hold_type,
                reason="Customer message matched a wrong-number, dispute, legal, damage, refund, or workmanship safety rule.",
                severity="CRITICAL",
            )
            if hold_type == "WRONG_NUMBER" and case.get("recipient_phone_e164"):
                with transaction() as conn:
                    upsert_sms_consent(
                        conn,
                        organization_id=str(job["organization_id"]),
                        job_id=str(job["id"]),
                        phone_e164=str(case["recipient_phone_e164"]),
                        status="OPTED_OUT",
                        source="WRONG_NUMBER_REPORT",
                        captured_at=datetime.now(UTC),
                        evidence={"inbound_message_id": message_id, "reported_by_recipient": True},
                    )
                    audit(
                        conn,
                        str(job["organization_id"]),
                        "CUSTOMER",
                        str(case["recipient_phone_e164"]),
                        "SMS_WRONG_NUMBER_REMOVED",
                        "workflow_job",
                        str(job["id"]),
                        {"message_id": message_id},
                    )
                reply = (
                    "Floodman: Thank you. We removed this number from account messages. "
                    "No further Floodman texts will be sent to it."
                )
            self._send_sms_once(
                thread=thread,
                job=job,
                case=case,
                message_kind="ESCALATION_ACK",
                dedupe_key=f"escalation-ack:{message_id}",
                body=reply,
                bypass_rate_limit=True,
                bypass_consent=hold_type == "WRONG_NUMBER",
            )
            return

        sanitized_history = [
            {"direction": item["direction"], "body": str(item["body"])[:1000]}
            for item in history
            if item["channel"] == "SMS"
        ]
        decision = self.ai.classify(
            {
                "message_id": message_id,
                "customer_message": body[:3000],
                "account": {
                    "has_balance": int(case["current_balance_cents"]) > 0,
                    "is_past_due": case["due_at"] <= datetime.now(UTC),
                    "status": str(case["status"]),
                    "payment_terms": "DUE_UPON_RECEIPT",
                },
                "conversation": sanitized_history,
            }
        )
        controlled = enforce_ai_decision(
            decision,
            min_confidence=self.settings.messaging_ai_min_confidence,
            auto_low=self.settings.messaging_ai_auto_reply_low_risk,
            auto_medium=self.settings.messaging_ai_auto_reply_medium_risk,
        )
        action = str(controlled["proposed_action"])
        policy_result = "AUTO_ALLOWED" if not controlled["human_review_required"] else "HUMAN_REVIEW_REQUIRED"
        with transaction() as conn:
            record_ai_message_decision(
                conn,
                thread_id=str(thread["id"]),
                inbound_message_id=message_id,
                provider=str(controlled.get("provider") or "deterministic"),
                model=str(controlled.get("model") or "") or None,
                decision=controlled,
                policy_result=policy_result,
            )

        reply = ""
        if controlled["human_review_required"] or action == "PAUSE_AND_ESCALATE":
            reply = self._pause_and_alert(
                job=job,
                case=case,
                thread=thread,
                inbound=inbound,
                hold_type="CALLBACK" if action == "CREATE_CALLBACK" else "MANUAL",
                reason=f"AI triage requires staff review. Intent: {controlled.get('intent','UNKNOWN')}.",
            )
        elif action == "REPORT_BALANCE":
            reply = (
                f"Floodman: The verified remaining balance for invoice {case['invoice_number']} is "
                f"{money(int(case['current_balance_cents']), str(case['currency']))}. "
                f"View or pay securely: {self.portal_url(job)}"
            )
        elif action == "REPORT_DUE_DATE":
            reply = (
                f"Floodman: Invoice {case['invoice_number']} was due upon receipt when it was issued. "
                f"Current balance: {money(int(case['current_balance_cents']), str(case['currency']))}. "
                f"Details: {self.portal_url(job)}"
            )
        elif action in {"RESEND_PAYMENT_LINK", "RESEND_INVOICE"}:
            reply = f"Floodman: Here is your secure invoice and payment link: {self.portal_url(job)}"
        elif action == "ACKNOWLEDGE_PAID_CLAIM":
            from .repository import enqueue

            self._pause_and_alert(
                job=job,
                case=case,
                thread=thread,
                inbound=inbound,
                hold_type="PAYMENT_REVIEW",
                reason=(
                    "Customer reported that payment was already made. Automated reminders are paused "
                    "while the live Square record is reconciled."
                ),
                severity="WARNING",
            )
            with transaction() as conn:
                enqueue(conn, job_id, "RECONCILE_JOB_PAYMENTS", {"reason": "customer_claimed_paid", "message_id": message_id})
            reply = (
                "Thank you. We paused automated reminders and are checking the live Square payment record. "
                "Our office will review any mismatch."
            )
        elif action == "CREATE_CALLBACK":
            reply = self._pause_and_alert(
                job=job,
                case=case,
                thread=thread,
                inbound=inbound,
                hold_type="CALLBACK",
                reason="Customer requested a callback.",
            )
        elif action == "CREATE_PROMISE_TO_PAY":
            promised = validate_promise_date(
                controlled.get("promise_to_pay_date"),
                today=datetime.now(UTC).date(),
                max_days=self.settings.ar_promise_max_days,
            )
            if not promised:
                reply = self._pause_and_alert(
                    job=job,
                    case=case,
                    thread=thread,
                    inbound=inbound,
                    hold_type="MANUAL",
                    reason="Customer proposed a payment date that could not be safely validated.",
                )
            else:
                paused_until = promise_pause_until(
                    promised,
                    str(case["customer_timezone"]),
                    self.settings.ar_send_start_local,
                )
                with transaction() as conn:
                    current_case = get_ar_case(conn, str(case["id"]), for_update=True)
                    create_payment_promise(
                        conn,
                        case=current_case,
                        promised_date=promised,
                        promised_amount_cents=None,
                        source_message_id=message_id,
                        created_by="CUSTOMER_SMS",
                        paused_until=paused_until,
                    )
                reply = (
                    f"Thank you. We recorded your expected payment date as {promised.strftime('%B %d, %Y')}. "
                    "Automated reminders are paused through that date. This does not change the invoice terms."
                )
        elif action == "ANSWER_APPROVED_FAQ":
            reply = str(controlled.get("reply_draft") or "").strip()
        elif action == "NO_ACTION":
            reply = ""
        if reply:
            self._send_sms_once(
                thread=thread,
                job=job,
                case=case,
                message_kind="AI_ASSISTED_REPLY",
                dedupe_key=f"inbound-reply:{message_id}",
                body=reply[:1500],
                bypass_rate_limit=True,
            )

    def send_help_reply(self, job_id: str, message_id: str) -> None:
        with transaction() as conn:
            job = get_job(conn, job_id)
            case = get_ar_case_by_job(conn, job_id)
            inbound = get_message_event(conn, message_id)
            thread = get_message_thread(conn, str(inbound["thread_id"]))
        if case:
            self.send_help(job=job, case=case, thread=thread, message_id=message_id)

    def send_help(self, *, job: dict[str, Any], case: dict[str, Any], thread: dict[str, Any], message_id: str) -> None:
        self._send_sms_once(
            thread=thread,
            job=job,
            case=case,
            message_kind="HELP_REPLY",
            dedupe_key=f"help-reply:{message_id}",
            body=help_sms(),
            bypass_rate_limit=True,
            bypass_consent=True,
        )

    def send_manual_reply(self, *, thread_id: str, body: str, actor: str) -> dict[str, Any]:
        with transaction() as conn:
            thread = get_message_thread(conn, thread_id)
            if not thread.get("job_id") or not thread.get("ar_case_id"):
                raise ValueError("Message thread is not linked to an A/R case")
            job = get_job(conn, str(thread["job_id"]))
            case = get_ar_case(conn, str(thread["ar_case_id"]))
        event = self._send_sms_once(
            thread=thread,
            job=job,
            case=case,
            message_kind="MANUAL_STAFF_REPLY",
            dedupe_key=f"manual-reply:{thread_id}:{datetime.now(UTC).isoformat()}:{actor}",
            body=body[:1500],
            bypass_rate_limit=True,
        )
        with transaction() as conn:
            audit(
                conn,
                str(job["organization_id"]),
                "STAFF",
                actor,
                "MANUAL_SMS_SENT",
                "message_thread",
                thread_id,
                {"message_event_id": str((event or {}).get("id") or "")},
            )
        return event or {}


def total_paid_cents_value(*, job_id: str, paid_delta: int, case: dict[str, Any]) -> str:
    """Stable payment-message marker without exposing provider identifiers in customer text."""
    return f"{job_id}:{int(case['current_balance_cents'])}:{paid_delta}"
