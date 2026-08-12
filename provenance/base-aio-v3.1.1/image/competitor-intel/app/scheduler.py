from __future__ import annotations

import logging
import signal
import time

from .config import get_settings
from .service import claim_due_target, record_error, run_target

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
stop = False


def halt(signum: int, frame: object) -> None:
    global stop
    stop = True


def main() -> None:
    settings = get_settings()
    signal.signal(signal.SIGTERM, halt)
    signal.signal(signal.SIGINT, halt)
    while not stop:
        target = claim_due_target()
        if not target:
            time.sleep(30)
            continue
        try:
            result = run_target(settings, str(target["id"]))
            logger.info("competitor target processed", extra={"target_id": str(target["id"]), "unchanged": result.get("unchanged")})
        except Exception as exc:  # noqa: BLE001 - scheduler boundary
            record_error(str(target["id"]), str(exc))
            logger.exception("competitor target failed", extra={"target_id": str(target["id"])})


if __name__ == "__main__":
    main()
