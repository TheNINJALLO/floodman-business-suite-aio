from __future__ import annotations

import logging
import signal
import time
from urllib.parse import urlparse

import httpx

from .config import get_settings
from .safe_web import UnsafeTarget
from .service import claim_due_target, record_error, run_target

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("floodman.competitor.scheduler")
stop = False


def halt(signum: int, frame: object) -> None:
    global stop
    stop = True


def friendly_error(target: dict[str, object], exc: Exception) -> str:
    raw = str(exc).strip() or exc.__class__.__name__
    host = (urlparse(str(target.get("url") or "")).hostname or "the configured host").lower()
    lowered = raw.lower()
    if isinstance(exc, UnsafeTarget):
        return f"Floodman rejected {host}: {raw}"
    if "certificate_verify_failed" in lowered or "certificate verify failed" in lowered or "hostname mismatch" in lowered:
        if host in {"groundworks.co", "www.groundworks.co"}:
            return (
                "TLS certificate hostname mismatch for groundworks.co. "
                "Edit this competitor monitor and use https://www.groundworks.com/. "
                "Floodman kept certificate verification enabled."
            )
        return (
            f"TLS certificate validation failed for {host}. Verify the canonical HTTPS URL. "
            "Floodman kept certificate verification enabled."
        )
    if isinstance(exc, httpx.TimeoutException) or "timeout" in lowered:
        return f"The scan of {host} timed out. Floodman will retry later."
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{host} returned HTTP {exc.response.status_code} during the scheduled scan."
    if isinstance(exc, httpx.ConnectError) or "connection refused" in lowered:
        return f"Floodman could not connect to {host}. The monitor remains enabled for a later retry."
    return raw[:1800]


def main() -> None:
    settings = get_settings()
    signal.signal(signal.SIGTERM, halt)
    signal.signal(signal.SIGINT, halt)
    while not stop:
        try:
            target = claim_due_target()
        except Exception as exc:
            logger.warning("Competitor database is temporarily unavailable: %s", exc)
            time.sleep(10)
            continue
        if not target:
            time.sleep(30)
            continue
        try:
            result = run_target(settings, str(target["id"]))
            logger.info(
                "Competitor target processed: %s (unchanged=%s)",
                target.get("name") or target.get("url") or target.get("id"),
                result.get("unchanged"),
            )
        except Exception as exc:
            message = friendly_error(target, exc)
            try:
                record_error(str(target["id"]), message)
            except Exception as record_exc:
                logger.warning("Could not record competitor error: %s", record_exc)
            logger.warning(
                "Competitor target skipped: %s — %s",
                target.get("name") or target.get("url") or target.get("id"),
                message,
            )


if __name__ == "__main__":
    main()
