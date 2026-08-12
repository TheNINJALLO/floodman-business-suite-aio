from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from sqlalchemy import text

from .analyzer import analyze, changes
from .config import Settings
from .db import transaction
from .extract import extract_page
from .safe_web import fetch_page
from .security import signed_headers


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def create_target(data: dict[str, Any]) -> dict[str, Any]:
    with transaction() as conn:
        row = conn.execute(
            text("""
                INSERT INTO competitor_targets(name,url,category,additional_paths,frequency_hours)
                VALUES (:name,:url,:category,CAST(:paths AS jsonb),:frequency)
                ON CONFLICT (organization_id,url) DO UPDATE SET
                  name=EXCLUDED.name,category=EXCLUDED.category,additional_paths=EXCLUDED.additional_paths,
                  frequency_hours=EXCLUDED.frequency_hours,enabled=true
                RETURNING *
            """),
            {
                "name": data["name"], "url": data["url"], "category": data.get("category"),
                "paths": _json(data.get("additional_paths", [])), "frequency": data["frequency_hours"],
            },
        ).mappings().one()
        return dict(row)


def get_target(target_id: str) -> dict[str, Any] | None:
    with transaction() as conn:
        row = conn.execute(
            text("SELECT * FROM competitor_targets WHERE id=CAST(:id AS uuid)"),
            {"id": target_id},
        ).mappings().first()
        return dict(row) if row else None


def update_target(target_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"name", "url", "category", "additional_paths", "frequency_hours", "enabled"}
    values = {key: value for key, value in data.items() if key in allowed and value is not None}
    if not values:
        return get_target(target_id)
    assignments: list[str] = []
    params: dict[str, Any] = {"id": target_id}
    for key, value in values.items():
        if key == "additional_paths":
            assignments.append("additional_paths=CAST(:additional_paths AS jsonb)")
            params[key] = _json(value)
        else:
            assignments.append(f"{key}=:{key}")
            params[key] = str(value) if key == "url" else value
    assignments.extend(["updated_at=now()", "next_run_at=LEAST(next_run_at, now())"])
    with transaction() as conn:
        row = conn.execute(
            text(f"UPDATE competitor_targets SET {', '.join(assignments)} WHERE id=CAST(:id AS uuid) RETURNING *"),
            params,
        ).mappings().first()
        return dict(row) if row else None


def delete_target(target_id: str) -> bool:
    with transaction() as conn:
        result = conn.execute(
            text("DELETE FROM competitor_targets WHERE id=CAST(:id AS uuid)"),
            {"id": target_id},
        )
        return bool(result.rowcount)


def list_targets() -> list[dict[str, Any]]:
    with transaction() as conn:
        return [dict(row) for row in conn.execute(text("SELECT * FROM competitor_targets ORDER BY name")).mappings().all()]


def list_reports(limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 200))
    with transaction() as conn:
        rows = conn.execute(
            text("""
                SELECT r.id,r.target_id,t.name AS target_name,t.url,r.report,r.change_summary,r.status,r.created_at
                FROM competitor_reports r
                JOIN competitor_targets t ON t.id=r.target_id
                ORDER BY r.created_at DESC LIMIT :limit
            """),
            {"limit": safe_limit},
        ).mappings().all()
        return [dict(row) for row in rows]


def get_report(report_id: str) -> dict[str, Any] | None:
    with transaction() as conn:
        row = conn.execute(
            text("""
                SELECT r.*,t.name AS target_name,t.url AS target_url,s.evidence,s.extracted_data,s.model
                FROM competitor_reports r
                JOIN competitor_targets t ON t.id=r.target_id
                JOIN competitor_snapshots s ON s.id=r.snapshot_id
                WHERE r.id=CAST(:id AS uuid)
            """),
            {"id": report_id},
        ).mappings().first()
        return dict(row) if row else None


def claim_due_target() -> dict[str, Any] | None:
    with transaction() as conn:
        row = conn.execute(
            text("""
                WITH candidate AS (
                  SELECT id FROM competitor_targets
                  WHERE enabled=true AND next_run_at <= now()
                  ORDER BY next_run_at FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE competitor_targets t SET
                  next_run_at=now() + (t.frequency_hours * interval '1 hour'),
                  last_run_at=now(), last_error=NULL
                FROM candidate WHERE t.id=candidate.id RETURNING t.*
            """)
        ).mappings().first()
        return dict(row) if row else None


def _daily_limit(settings: Settings) -> None:
    with transaction() as conn:
        count = int(conn.execute(text("SELECT count(*) FROM competitor_reports WHERE created_at >= now() - interval '24 hours'")).scalar_one())
    if count >= settings.max_runs_per_day:
        raise RuntimeError("Daily competitor-analysis limit reached")


def run_target(settings: Settings, target_id: str) -> dict[str, Any]:
    _daily_limit(settings)
    with transaction() as conn:
        target_row = conn.execute(text("SELECT * FROM competitor_targets WHERE id=CAST(:id AS uuid)"), {"id": target_id}).mappings().first()
        if not target_row:
            raise ValueError("Competitor target not found")
        target = dict(target_row)
        previous_row = conn.execute(
            text("SELECT * FROM competitor_snapshots WHERE target_id=CAST(:id AS uuid) ORDER BY created_at DESC LIMIT 1"),
            {"id": target_id},
        ).mappings().first()
        previous = dict(previous_row) if previous_row else None

    base_url = str(target["url"])
    robots: RobotFileParser | None = None
    try:
        robots_page = fetch_page(
            urljoin(base_url, "/robots.txt"),
            allow_http=settings.allow_http,
            max_bytes=min(settings.max_response_bytes, 512 * 1024),
            user_agent=settings.user_agent,
        )
        robots = RobotFileParser()
        robots.parse(robots_page.body.splitlines())
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {401, 403}:
            raise RuntimeError("Competitor site disallows access to robots.txt") from exc
    except Exception:
        # Missing or malformed robots files are recorded by the normal page evidence path.
        robots = None
    paths = [""] + list(target.get("additional_paths") or [])
    pages: list[dict[str, Any]] = []
    seen: set[str] = set()
    base_host = urlparse(base_url).hostname
    for path in paths[: settings.max_pages_per_target]:
        url = base_url if not path else urljoin(base_url.rstrip("/") + "/", str(path).lstrip("/"))
        if url in seen or urlparse(url).hostname != base_host:
            continue
        if robots is not None and not robots.can_fetch(settings.user_agent, url):
            continue
        seen.add(url)
        page = fetch_page(
            url,
            allow_http=settings.allow_http,
            max_bytes=settings.max_response_bytes,
            user_agent=settings.user_agent,
        )
        pages.append(extract_page(page.url, page.body, settings.max_analysis_chars // max(1, len(paths))))
    if not pages:
        raise RuntimeError("No competitor pages were fetched")

    extracted = {
        "pages": pages,
        "headings": sorted({h for page in pages for h in page["headings"]})[:250],
        "prices": sorted({p for page in pages for p in page["prices"]})[:100],
        "service_claims": sorted({c for page in pages for c in page["service_claims"]}),
    }
    canonical = _json(extracted).encode()
    content_hash = hashlib.sha256(canonical).hexdigest()
    if previous and previous["content_sha256"] == content_hash:
        return {"target_id": target_id, "unchanged": True, "snapshot_id": str(previous["id"])}

    previous_data = previous["extracted_data"] if previous else None
    diff = changes(previous_data, extracted)
    report, model = analyze(settings, target, extracted, diff)
    evidence = [
        {"url": page["url"], "sha256": page["sha256"], "title": page["title"], "captured_at": datetime.now(UTC).isoformat()}
        for page in pages
    ]
    with transaction() as conn:
        snapshot = conn.execute(
            text("""
                INSERT INTO competitor_snapshots(target_id,content_sha256,extracted_data,evidence,source_count,model)
                VALUES (CAST(:target_id AS uuid),:hash,CAST(:data AS jsonb),CAST(:evidence AS jsonb),:count,:model)
                ON CONFLICT (target_id,content_sha256) DO UPDATE SET model=EXCLUDED.model
                RETURNING *
            """),
            {"target_id": target_id, "hash": content_hash, "data": _json(extracted), "evidence": _json(evidence), "count": len(pages), "model": model},
        ).mappings().one()
        report_row = conn.execute(
            text("""
                INSERT INTO competitor_reports(target_id,snapshot_id,previous_snapshot_id,report,change_summary)
                VALUES (CAST(:target_id AS uuid),CAST(:snapshot_id AS uuid),CAST(:previous_id AS uuid),CAST(:report AS jsonb),CAST(:diff AS jsonb))
                RETURNING *
            """),
            {
                "target_id": target_id,
                "snapshot_id": str(snapshot["id"]),
                "previous_id": str(previous["id"]) if previous else None,
                "report": _json(report),
                "diff": _json(diff),
            },
        ).mappings().one()
        conn.execute(text("UPDATE competitor_targets SET last_error=NULL WHERE id=CAST(:id AS uuid)"), {"id": target_id})

    callback = {
        "target_id": target_id,
        "target_name": target["name"],
        "report_id": str(report_row["id"]),
        "report": report,
        "change_summary": diff,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    body = _json(callback).encode()
    try:
        with httpx.Client(timeout=20) as client:
            response = client.post(settings.callback_url, content=body, headers=signed_headers(settings.hmac_keys, body))
            response.raise_for_status()
    except Exception:
        # The report is durably stored. Callback failure must not duplicate research or erase evidence.
        pass
    return {"target_id": target_id, "unchanged": False, "report_id": str(report_row["id"]), "report": report, "change_summary": diff}


def record_error(target_id: str, error: str) -> None:
    with transaction() as conn:
        conn.execute(text("UPDATE competitor_targets SET last_error=:error, next_run_at=LEAST(next_run_at, now() + interval '1 hour') WHERE id=CAST(:id AS uuid)"), {"id": target_id, "error": error[:4000]})
