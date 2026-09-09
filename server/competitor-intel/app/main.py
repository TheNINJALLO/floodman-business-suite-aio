from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import ready
from .safe_web import UnsafeTarget
from .schemas import RunRequest, TargetCreate, TargetUpdate
from .security import AuthenticationError, verify
from .service import (
    create_target,
    delete_target,
    get_report,
    get_target,
    list_reports,
    list_targets,
    record_error,
    run_target,
    update_target,
)

settings = get_settings()
app = FastAPI(
    title="Floodman Competitor Intelligence",
    version="4.7.2",
    docs_url=None if os.getenv("FLOODMAN_ENV", "development").lower() == "production" else "/docs",
    redoc_url=None,
)


async def internal_auth(request: Request) -> str:
    body = await request.body()
    try:
        return verify(request.headers, body, settings.hmac_keys, settings.hmac_max_age_seconds)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _target_host(target: dict | None) -> str:
    return (urlparse(str((target or {}).get("url") or "")).hostname or "the configured competitor website").lower()


def _friendly_scan_error(target: dict | None, exc: Exception) -> tuple[int, str]:
    """Convert expected website failures into safe operator-facing messages.

    The competitor website is outside Floodman's control. DNS failures, TLS
    errors, robots restrictions, timeouts, and HTTP errors should not surface
    as an unexplained API 500 or a full traceback in the owner console.
    """

    raw = str(exc).strip() or exc.__class__.__name__
    lowered = raw.lower()
    host = _target_host(target)

    if isinstance(exc, UnsafeTarget):
        return 422, f"Floodman rejected {host}: {raw}"

    if "certificate_verify_failed" in lowered or "certificate verify failed" in lowered or "hostname mismatch" in lowered:
        if host in {"groundworks.co", "www.groundworks.co"}:
            return (
                422,
                "TLS certificate hostname mismatch for groundworks.co. Edit this monitor and use "
                "https://www.groundworks.com/. Floodman kept certificate verification enabled.",
            )
        return (
            422,
            f"TLS certificate validation failed for {host}. Confirm the monitor URL uses the website's canonical HTTPS hostname. "
            "Floodman kept certificate verification enabled.",
        )

    if isinstance(exc, httpx.TimeoutException) or "timed out" in lowered or "timeout" in lowered:
        return 504, f"The scan of {host} timed out. The monitor was left enabled and can be retried."

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {401, 403}:
            return 422, f"{host} denied the automated public-page request with HTTP {status}."
        if status == 404:
            return 422, f"A configured page on {host} returned HTTP 404. Review the monitor's additional paths."
        if status == 429:
            return 429, f"{host} rate-limited the scan. Wait before running it again."
        return 502, f"{host} returned HTTP {status} while Floodman was collecting public evidence."

    if isinstance(exc, httpx.ConnectError) or "connection refused" in lowered or "name or service not known" in lowered or "nodename nor servname" in lowered:
        return 502, f"Floodman could not connect to {host}. Verify the public URL and try again."

    if "daily competitor-analysis limit reached" in lowered:
        return 429, "The daily competitor-scan limit has been reached. Try again after the 24-hour window advances."

    if "competitor site disallows access" in lowered:
        return 422, f"{host} disallows this automated public-page scan through its robots policy."

    if "no competitor pages were fetched" in lowered:
        return 422, f"Floodman could not collect any permitted public pages from {host}. Review the base URL and additional paths."

    if isinstance(exc, ValueError) and "not found" in lowered:
        return 404, raw

    # Preserve enough information for diagnosis without exposing an internal
    # Python traceback to the browser.
    return 500, f"Competitor scan could not be completed for {host}: {raw[:1000]}"


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok", "service": "competitor-intel", "version": "4.7.2"}


@app.get("/health/ready")
def readiness() -> JSONResponse:
    value = ready()
    return JSONResponse({"status": "ready" if value else "not_ready", "database": value}, status_code=200 if value else 503)


@app.post("/internal/v1/targets")
def add_target(target: TargetCreate, actor: str = Depends(internal_auth)) -> dict:
    data = target.model_dump(mode="json")
    data["url"] = str(target.url)
    result = create_target(data)
    return {"id": str(result["id"]), "name": result["name"], "url": result["url"]}


@app.get("/internal/v1/targets")
def targets(actor: str = Depends(internal_auth)) -> list[dict]:
    return [{**item, "id": str(item["id"])} for item in list_targets()]


@app.get("/internal/v1/targets/{target_id}")
def target(target_id: str, actor: str = Depends(internal_auth)) -> dict:
    value = get_target(target_id)
    if not value:
        raise HTTPException(status_code=404, detail="Competitor target not found")
    return {**value, "id": str(value["id"])}


@app.put("/internal/v1/targets/{target_id}")
def edit_target(target_id: str, target: TargetUpdate, actor: str = Depends(internal_auth)) -> dict:
    data = target.model_dump(mode="json", exclude_unset=True)
    if target.url is not None:
        data["url"] = str(target.url)
    value = update_target(target_id, data)
    if not value:
        raise HTTPException(status_code=404, detail="Competitor target not found")
    return {**value, "id": str(value["id"])}


@app.delete("/internal/v1/targets/{target_id}")
def remove_target(target_id: str, actor: str = Depends(internal_auth)) -> dict[str, bool]:
    if not delete_target(target_id):
        raise HTTPException(status_code=404, detail="Competitor target not found")
    return {"deleted": True}


@app.get("/internal/v1/reports")
def reports(limit: int = 50, actor: str = Depends(internal_auth)) -> list[dict]:
    return [
        {**item, "id": str(item["id"]), "target_id": str(item["target_id"])}
        for item in list_reports(limit)
    ]


@app.get("/internal/v1/reports/{report_id}")
def report(report_id: str, actor: str = Depends(internal_auth)) -> dict:
    value = get_report(report_id)
    if not value:
        raise HTTPException(status_code=404, detail="Competitor report not found")
    return {
        **value,
        "id": str(value["id"]),
        "target_id": str(value["target_id"]),
        "snapshot_id": str(value["snapshot_id"]),
        "previous_snapshot_id": str(value["previous_snapshot_id"]) if value.get("previous_snapshot_id") else None,
    }


@app.post("/internal/v1/run")
def run(request: RunRequest, actor: str = Depends(internal_auth)) -> dict:
    target_value = get_target(request.target_id)
    if not target_value:
        raise HTTPException(status_code=404, detail="Competitor target not found")
    try:
        return run_target(settings, request.target_id)
    except Exception as exc:  # Website/network boundary; translate before returning to staff UI.
        status_code, message = _friendly_scan_error(target_value, exc)
        try:
            record_error(request.target_id, message)
        except Exception:
            # The scan error is still useful even when the error-record update
            # cannot be written during a transient database problem.
            pass
        raise HTTPException(status_code=status_code, detail=message) from exc
