from __future__ import annotations

import logging
import os
import signal
import socket
import time

from .config import get_settings
from .db import transaction
from .logging_json import configure_logging
from .repository import claim_outbox, complete_outbox, retry_outbox
from .service import PermanentEventError, WorkflowService

logger = logging.getLogger(__name__)
_stop = False


def _request_stop(signum: int, frame: object) -> None:
    global _stop
    _stop = True


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    service = WorkflowService(settings)
    logger.info("outbox worker started", extra={"worker_id": worker_id})
    try:
        while not _stop:
            with transaction() as conn:
                event = claim_outbox(conn, worker_id, settings.outbox_lock_seconds)
            if not event:
                time.sleep(settings.outbox_poll_seconds)
                continue
            try:
                service.handle(event)
            except PermanentEventError as exc:
                logger.error(
                    "outbox event requires manual review",
                    extra={"event_id": str(event["id"]), "event_type": event["event_type"], "error": str(exc)},
                )
                permanent = dict(event)
                permanent["attempts"] = settings.outbox_max_attempts
                with transaction() as conn:
                    retry_outbox(conn, permanent, str(exc), settings.outbox_max_attempts)
            except Exception as exc:  # noqa: BLE001 - worker boundary
                logger.exception(
                    "outbox event failed",
                    extra={"event_id": str(event["id"]), "event_type": event["event_type"]},
                )
                with transaction() as conn:
                    retry_outbox(conn, event, str(exc), settings.outbox_max_attempts)
            else:
                with transaction() as conn:
                    complete_outbox(conn, str(event["id"]))
    finally:
        service.close()
        logger.info("outbox worker stopped", extra={"worker_id": worker_id})


if __name__ == "__main__":
    main()
