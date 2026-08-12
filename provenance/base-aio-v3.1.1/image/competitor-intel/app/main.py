from __future__ import annotations

import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import ready
from .schemas import RunRequest, TargetCreate, TargetUpdate
from .security import AuthenticationError, verify
from .service import create_target, delete_target, get_report, get_target, list_reports, list_targets, run_target, update_target

settings = get_settings()
app = FastAPI(title="Floodman Competitor Intelligence", version="3.0.0", docs_url=None if os.getenv("FLOODMAN_ENV", "development").lower() == "production" else "/docs", redoc_url=None)


async def internal_auth(request: Request) -> str:
    body = await request.body()
    try:
        return verify(request.headers, body, settings.hmac_keys, settings.hmac_max_age_seconds)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok", "service": "competitor-intel"}


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
    return run_target(settings, request.target_id)
