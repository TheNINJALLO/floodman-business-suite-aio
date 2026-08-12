from __future__ import annotations

import logging
import os
import signal
import socket
import time
from datetime import UTC, datetime

from sqlalchemy import text

from .ar import parse_clock, zone
from .config import get_settings
from .db import transaction
from .logging_json import configure_logging
from .message_templates import money
from .repository import (
    ar_aging_summary,
    begin_ar_digest,
    claim_due_ar_case,
    create_staff_alert,
    enqueue,
    finish_ar_digest,
    get_job,
    mark_missed_promises,
    organization_ids_with_ar_cases,
)

logger = logging.getLogger(__name__)
_stop = False


def _request_stop(signum: int, frame: object) -> None:
    global _stop
    _stop = True


def _queue_due_cases(worker_id: str, lock_seconds: int) -> int:
    queued = 0
    while queued < 100:
        with transaction() as conn:
            case = claim_due_ar_case(conn, worker_id, lock_seconds)
            if not case:
                break
            enqueue(
                conn,
                str(case["job_id"]),
                "SEND_AR_REMINDER",
                {"ar_case_id": str(case["id"]), "reminder_count": int(case["reminder_count"])},
            )
        queued += 1
    return queued


def _queue_missed_promises(now: datetime) -> int:
    with transaction() as conn:
        missed = mark_missed_promises(conn, now.date())
        for promise in missed:
            job = get_job(conn, str(promise["job_id"]))
            alert = create_staff_alert(
                conn,
                organization_id=str(job["organization_id"]),
                job_id=str(job["id"]),
                ar_case_id=str(promise["ar_case_id"]),
                thread_id=None,
                alert_type="MISSED_PROMISE_TO_PAY",
                severity="WARNING",
                title=f"Promise to pay missed for invoice F-{job['invoice_number']}-FINAL",
                body=f"The customer promised payment on {promise['promised_date']}; the verified balance remains open.",
                metadata={"payment_promise_id": str(promise["id"])},
            )
            enqueue(conn, str(job["id"]), "SEND_STAFF_ALERT", {"alert_id": str(alert["id"])})
        return len(missed)


def _queue_daily_digests(now: datetime) -> int:
    settings = get_settings()
    local = now.astimezone(zone(settings.ar_timezone))
    digest_time = parse_clock(settings.ar_digest_local_time)
    if local.time().replace(tzinfo=None) < digest_time:
        return 0
    queued = 0
    with transaction() as conn:
        for organization_id in organization_ids_with_ar_cases(conn):
            run = begin_ar_digest(conn, organization_id, local.date())
            if not run:
                continue
            try:
                summary = ar_aging_summary(conn, now, organization_id)
                title = f"Floodman daily A/R digest | {local.date().isoformat()}"
                body = (
                    f"Open: {summary['open_count']} invoices / {money(summary['open_cents'])}\n"
                    f"0-7 days: {summary['days_0_7_count']} / {money(summary['days_0_7_cents'])}\n"
                    f"8-14 days: {summary['days_8_14_count']} / {money(summary['days_8_14_cents'])}\n"
                    f"15-30 days: {summary['days_15_30_count']} / {money(summary['days_15_30_cents'])}\n"
                    f"31+ days: {summary['days_31_plus_count']} / {money(summary['days_31_plus_cents'])}\n"
                    f"Disputes: {summary['disputed_count']} | Promises to pay: {summary['promise_count']}"
                )
                alert = create_staff_alert(
                    conn,
                    organization_id=organization_id,
                    job_id=None,
                    ar_case_id=None,
                    thread_id=None,
                    alert_type="DAILY_AR_DIGEST",
                    severity="INFO",
                    title=title,
                    body=body,
                    metadata=summary,
                )
                # Outbox aggregates require a job UUID. Use the oldest open case's job if available.
                row = conn.execute(
                    text("SELECT job_id::text FROM ar_cases WHERE organization_id=:organization_id ORDER BY created_at LIMIT 1"),
                    {"organization_id": organization_id},
                ).first()
                if row:
                    enqueue(conn, str(row[0]), "SEND_STAFF_ALERT", {"alert_id": str(alert["id"])})
                    finish_ar_digest(conn, str(run["id"]), "SENT", summary)
                    queued += 1
                else:
                    finish_ar_digest(conn, str(run["id"]), "FAILED", summary, "No A/R job available for outbox aggregate")
            except Exception as exc:
                finish_ar_digest(conn, str(run["id"]), "FAILED", {}, str(exc))
                raise
    return queued


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    worker_id = f"ar:{socket.gethostname()}:{os.getpid()}"
    logger.info("A/R scheduler started", extra={"worker_id": worker_id})
    while not _stop:
        started = time.monotonic()
        try:
            now = datetime.now(UTC)
            missed = _queue_missed_promises(now)
            queued = _queue_due_cases(worker_id, settings.outbox_lock_seconds)
            digests = _queue_daily_digests(now)
            if missed or queued or digests:
                logger.info(
                    "A/R scheduler cycle",
                    extra={"missed_promises": missed, "reminders_queued": queued, "digests_queued": digests},
                )
        except Exception:
            logger.exception("A/R scheduler cycle failed")
        elapsed = time.monotonic() - started
        time.sleep(max(1.0, settings.ar_scan_seconds - elapsed))
    logger.info("A/R scheduler stopped", extra={"worker_id": worker_id})


if __name__ == "__main__":
    main()
