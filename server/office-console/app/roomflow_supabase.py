from __future__ import annotations

import hashlib
import json
import ssl
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .project_plans import merge_project_plan
from .store import OfficeStore

DEFAULT_ROOMFLOW_SUPABASE_URL = "https://bjqvowghqajwudgyqnau.supabase.co"
DEFAULT_ROOMFLOW_SUPABASE_ANON_KEY = "sb_publishable_F3R00Fm2TVxOIPzT5-SSxw_dxLLcKu7"
_SOURCE = "ROOMFLOW_SUPABASE_IMPORT"
_PROVIDER = "roomflow-supabase"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _text(value: Any, limit: int = 12_000) -> str:
    return str(value or "").strip()[:limit]


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _cents(row: dict[str, Any], cents_key: str, amount_key: str, default: int = 0) -> int:
    if row.get(cents_key) not in (None, ""):
        return max(0, _int(row.get(cents_key), default))
    return max(0, int(round(_float(row.get(amount_key), default / 100) * 100)))


def _stable_id(kind: str, source_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"floodman:{_PROVIDER}:{kind}:{source_id}"))


def _workspace_id(source_organization_id: str) -> str:
    source = _text(source_organization_id, 160) or "local-default"
    return _stable_id("workspace", source)


def _workspace_selection_id(user_id: str) -> str:
    return _stable_id("workspace-selection", _text(user_id, 160) or "anonymous")


def workspace_public(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record.get(key)
        for key in (
            "id", "name", "timezone", "status", "source", "imported", "is_default",
            "roomflow_organization_id", "source_organization_id", "membership_role_id",
            "source_created_at", "source_updated_at", "created_at", "updated_at",
        )
        if record.get(key) is not None
    }


def _workspace_sort_key(record: dict[str, Any]) -> tuple[int, str, str]:
    source_org = _text(record.get("roomflow_organization_id") or record.get("source_organization_id"), 160)
    # Imported companies should win over a synthetic fallback workspace.
    priority = 0 if source_org else (1 if bool(record.get("imported")) else 2)
    return (priority, _text(record.get("name"), 300).casefold(), str(record.get("id") or ""))


def ensure_roomflow_workspaces(store: OfficeStore, *, actor_id: str = "") -> list[dict[str, Any]]:
    """Persist and repair selectable RoomFlow workspaces.

    v4.6.2 imported the organization identifier onto jobs and related rows but
    did not create an actual selectable workspace. This function is deliberately
    idempotent: it reconstructs missing workspace rows from those identifiers,
    backfills workspace_id across already imported records, and creates one safe
    Floodman workspace only when no company can be recovered.
    """
    existing = {str(record.get("id") or ""): record for record in store.records("roomflow_workspaces") if record.get("id")}
    by_source: dict[str, str] = {}
    for record in existing.values():
        source_org = _text(record.get("roomflow_organization_id") or record.get("source_organization_id"), 160)
        if source_org:
            by_source[source_org] = str(record["id"])

    source_names: dict[str, str] = {}
    record_kinds = ("contacts", "properties", "catalog_items", "estimates", "roomflow_jobs")
    records_by_kind = {kind: store.records(kind) for kind in record_kinds}
    for kind, records in records_by_kind.items():
        for record in records:
            source_org = _text(record.get("roomflow_organization_id"), 160)
            if source_org:
                # Never infer a company name from a customer, property, job, or
                # catalog item. Older v4.6.2 rows carried the organization ID but
                # not always the organization name; the next idempotent import
                # supplies the authoritative Supabase organization record.
                candidate_name = _text(
                    record.get("roomflow_organization_name")
                    or record.get("workspace_name"),
                    300,
                )
                source_names.setdefault(source_org, candidate_name)

    workspace_upserts: list[dict[str, Any]] = []
    for source_org, inferred_name in source_names.items():
        workspace_id = by_source.get(source_org) or _workspace_id(source_org)
        by_source[source_org] = workspace_id
        current = existing.get(workspace_id) or {}
        workspace_upserts.append({
            "id": workspace_id,
            "name": _text(current.get("name") or inferred_name, 300)
            or (_text(store.profile().get("company_name"), 300) or "Floodman")
            + (f" · imported {source_org[:6]}" if len(source_names) > 1 else ""),
            "timezone": _text(current.get("timezone"), 80) or _text(store.profile().get("timezone"), 80) or "America/Detroit",
            "status": "ACTIVE",
            "imported": True,
            "is_default": bool(current.get("is_default", False)),
            "roomflow_organization_id": source_org,
            "source_organization_id": source_org,
            "source": current.get("source") or _SOURCE,
        })

    if workspace_upserts:
        store.bulk_upsert_records({"roomflow_workspaces": workspace_upserts}, actor_id=actor_id or None)
        existing = {str(record.get("id") or ""): record for record in store.records("roomflow_workspaces") if record.get("id")}

    if not existing:
        local_id = _workspace_id("local-default")
        local = store.create_record(
            "roomflow_workspaces",
            {
                "id": local_id,
                "name": _text(store.profile().get("company_name"), 300) or "Floodman",
                "timezone": _text(store.profile().get("timezone"), 80) or "America/Detroit",
                "status": "ACTIVE",
                "imported": False,
                "is_default": True,
                "source": "FLOODMAN_ROOMFLOW_NATIVE",
            },
            actor_id=actor_id or None,
        )
        existing = {local_id: local}

    # Map linked estimates and identity records through their imported job.
    job_workspace_by_local_id: dict[str, str] = {}
    job_workspace_by_source_id: dict[str, str] = {}
    default_workspace_id = sorted(existing.values(), key=_workspace_sort_key)[0]["id"]
    for job in records_by_kind["roomflow_jobs"]:
        source_org = _text(job.get("roomflow_organization_id"), 160)
        workspace_id = _text(job.get("workspace_id"), 160)
        if source_org:
            workspace_id = by_source.get(source_org) or _workspace_id(source_org)
        if not workspace_id:
            workspace_id = str(default_workspace_id)
        job_workspace_by_local_id[str(job.get("id") or "")] = workspace_id
        for source_key in (job.get("roomflow_source_id"), job.get("roomflow_job_id")):
            if source_key:
                job_workspace_by_source_id[_text(source_key, 160)] = workspace_id

    changed: dict[str, list[dict[str, Any]]] = {kind: [] for kind in record_kinds}
    for kind, records in records_by_kind.items():
        for record in records:
            workspace_id = _text(record.get("workspace_id"), 160)
            source_org = _text(record.get("roomflow_organization_id"), 160)
            if source_org:
                workspace_id = by_source.get(source_org) or _workspace_id(source_org)
            if not workspace_id and kind == "estimates":
                workspace_id = job_workspace_by_local_id.get(_text(record.get("roomflow_job_id"), 160), "")
                if not workspace_id:
                    workspace_id = job_workspace_by_source_id.get(_text(record.get("roomflow_job_source_id"), 160), "")
            if not workspace_id and kind in {"contacts", "properties"}:
                # Recover identity records from the imported jobs that reference them.
                record_id = str(record.get("id") or "")
                link_field = "contact_id" if kind == "contacts" else "property_id"
                linked = next(
                    (
                        job_workspace_by_local_id.get(str(job.get("id") or ""), "")
                        for job in records_by_kind["roomflow_jobs"]
                        if str(job.get(link_field) or "") == record_id
                    ),
                    "",
                )
                workspace_id = linked
            if not workspace_id and kind in {"roomflow_jobs", "catalog_items"} and str(record.get("source") or "").startswith("ROOMFLOW"):
                workspace_id = str(default_workspace_id)
            if workspace_id and workspace_id != _text(record.get("workspace_id"), 160):
                changed[kind].append({**record, "workspace_id": workspace_id})
    changed = {kind: records for kind, records in changed.items() if records}
    if changed:
        store.bulk_upsert_records(changed, actor_id=actor_id or None)

    return sorted(store.records("roomflow_workspaces"), key=_workspace_sort_key)


def selected_roomflow_workspace_id(
    store: OfficeStore,
    user_id: str,
    *,
    preferred_workspace_id: str = "",
    actor_id: str = "",
) -> str:
    workspaces = ensure_roomflow_workspaces(store, actor_id=actor_id or user_id)
    valid_ids = {str(record.get("id") or "") for record in workspaces}
    preferred = _text(preferred_workspace_id, 160)
    selection_id = _workspace_selection_id(user_id)
    selection = store.record("roomflow_workspace_selections", selection_id)
    selected = preferred if preferred in valid_ids else _text((selection or {}).get("workspace_id"), 160)
    if selected not in valid_ids:
        selected = str(workspaces[0]["id"])
    values = {
        "id": selection_id,
        "user_id": user_id,
        "workspace_id": selected,
        "source": "FLOODMAN_ROOMFLOW_NATIVE",
    }
    if selection:
        store.update_record("roomflow_workspace_selections", selection_id, values, actor_id=actor_id or user_id)
    else:
        store.create_record("roomflow_workspace_selections", values, actor_id=actor_id or user_id)
    return selected


def select_roomflow_workspace(store: OfficeStore, user_id: str, workspace_id: str, *, actor_id: str = "") -> dict[str, Any]:
    workspaces = ensure_roomflow_workspaces(store, actor_id=actor_id or user_id)
    selected = next((record for record in workspaces if str(record.get("id") or "") == workspace_id), None)
    if not selected:
        raise KeyError(workspace_id)
    selected_roomflow_workspace_id(
        store,
        user_id,
        preferred_workspace_id=workspace_id,
        actor_id=actor_id or user_id,
    )
    return selected


def create_roomflow_workspace(
    store: OfficeStore,
    *,
    name: str,
    timezone: str,
    user_id: str,
    actor_id: str,
) -> dict[str, Any]:
    clean_name = _text(name, 300)
    if len(clean_name) < 2:
        raise ValueError("Enter a company name with at least two characters.")
    requested_timezone = _text(timezone, 80) or "America/Detroit"
    if requested_timezone != "America/Detroit":
        raise ValueError("Floodman company workspaces use Eastern Time (Detroit).")
    for existing in ensure_roomflow_workspaces(store, actor_id=actor_id):
        if _text(existing.get("name"), 300).casefold() == clean_name.casefold():
            select_roomflow_workspace(store, user_id, str(existing["id"]), actor_id=actor_id)
            return existing
    workspace = store.create_record(
        "roomflow_workspaces",
        {
            "name": clean_name,
            "timezone": "America/Detroit",
            "status": "ACTIVE",
            "imported": False,
            "is_default": False,
            "source": "FLOODMAN_ROOMFLOW_NATIVE",
        },
        actor_id=actor_id,
    )
    select_roomflow_workspace(store, user_id, str(workspace["id"]), actor_id=actor_id)
    return workspace


def _chunks(values: Iterable[str], size: int = 80) -> Iterable[list[str]]:
    bucket: list[str] = []
    for value in values:
        if not value:
            continue
        bucket.append(value)
        if len(bucket) >= size:
            yield bucket
            bucket = []
    if bucket:
        yield bucket


def _address(row: dict[str, Any]) -> str:
    explicit = _text(row.get("property_address") or row.get("address") or row.get("service_address"), 500)
    if explicit:
        return explicit
    locality = ", ".join(
        part for part in (
            _text(row.get("city"), 120),
            " ".join(part for part in (_text(row.get("state"), 40), _text(row.get("postal_code"), 32)) if part),
        ) if part
    )
    return locality


def _status(value: Any, default: str = "DRAFT") -> str:
    normalized = _text(value, 80).replace("-", "_").replace(" ", "_").upper()
    aliases = {
        "NEW": "DRAFT",
        "NOT_STARTED": "DRAFT",
        "READY": "READY_FOR_REVIEW",
        "APPROVED": "ACCEPTED",
        "AUTHORISED": "ACCEPTED",
        "AUTHORIZED": "ACCEPTED",
        "DECLINED": "DECLINED",
        "CANCELLED": "CANCELED",
    }
    return aliases.get(normalized, normalized or default)


def _infer_project_category(job: dict[str, Any], lines: list[dict[str, Any]]) -> str:
    words = " ".join(
        [
            _text(job.get("name"), 500),
            _text(job.get("issue_description"), 2_000),
            *[_text(line.get("category"), 160) for line in lines],
            *[_text(line.get("name"), 300) for line in lines],
        ]
    ).casefold()
    if "crawl" in words or "encapsulation" in words or "vapor barrier" in words:
        return "crawlspace-encapsulation"
    if "mold" in words or "microbial" in words or "antimicrobial" in words:
        return "mold-remediation"
    if "foundation" in words or "carbon fiber" in words or "wall reinforcement" in words:
        return "foundation-repair"
    if "waterproof" in words or "sump" in words or "drain" in words or "water management" in words:
        return "basement-waterproofing"
    if "water damage" in words or "dry out" in words or "extraction" in words:
        return "water-damage-restoration"
    if "demolition" in words or "demo" in words or "rebuild" in words:
        return "demolition-and-rebuild"
    if "inspection" in words or "testing" in words:
        return "inspection-and-testing"
    return "general-restoration"


class RoomFlowSupabaseError(RuntimeError):
    pass


class RoomFlowSupabaseClient:
    """Minimal password-authenticated Supabase client used only for one-time migration.

    The publishable key is public by design. The user password and returned access
    token are retained only in memory for the duration of one import request.
    """

    def __init__(self, base_url: str, anon_key: str, *, timeout: int = 45) -> None:
        self.base_url = base_url.rstrip("/")
        self.anon_key = anon_key.strip()
        self.timeout = timeout
        self.access_token = ""
        self.user_id = ""
        self.warnings: list[str] = []
        self._ssl = ssl.create_default_context()

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        optional: bool = False,
    ) -> tuple[Any, dict[str, str]]:
        suffix = ""
        if query:
            suffix = "?" + urlencode(query, doseq=True, safe="(),.*:-_")
        url = f"{self.base_url}{path}{suffix}"
        request_headers = {
            "apikey": self.anon_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Floodman-RoomFlow-Importer/4.7.1",
        }
        if self.access_token:
            request_headers["Authorization"] = f"Bearer {self.access_token}"
        if headers:
            request_headers.update(headers)
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(url, data=payload, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout, context=self._ssl) as response:
                raw = response.read()
                result = json.loads(raw.decode("utf-8")) if raw else None
                return result, {key.lower(): value for key, value in response.headers.items()}
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")[:2_000]
            message = ""
            try:
                parsed = json.loads(raw)
                message = _text(parsed.get("msg") or parsed.get("message") or parsed.get("error_description") or parsed.get("error"), 500)
            except Exception:
                message = _text(raw, 500)
            if optional and exc.code in {400, 404, 406}:
                self.warnings.append(f"Skipped unavailable Supabase resource {path}: {message or f'HTTP {exc.code}'}")
                return [], {}
            if exc.code in {400, 401, 403} and path.startswith("/auth/"):
                raise RoomFlowSupabaseError("RoomFlow Supabase did not accept that email and password.") from exc
            raise RoomFlowSupabaseError(f"RoomFlow Supabase request failed for {path}: {message or f'HTTP {exc.code}'}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RoomFlowSupabaseError("Floodman could not reach the original RoomFlow Supabase project.") from exc

    def sign_in(self, email: str, password: str) -> dict[str, Any]:
        result, _ = self._request(
            "/auth/v1/token",
            method="POST",
            query={"grant_type": "password"},
            body={"email": email.strip().lower(), "password": password},
        )
        if not isinstance(result, dict) or not result.get("access_token"):
            raise RoomFlowSupabaseError("RoomFlow Supabase did not return an authenticated session.")
        self.access_token = _text(result.get("access_token"), 10_000)
        user = result.get("user") if isinstance(result.get("user"), dict) else {}
        self.user_id = _text(user.get("id"), 100)
        if not self.user_id:
            raise RoomFlowSupabaseError("RoomFlow Supabase did not identify the signed-in user.")
        return user

    def table_rows(
        self,
        table: str,
        *,
        filters: dict[str, str] | None = None,
        select: str = "*",
        optional: bool = False,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        page_size = 1_000
        while True:
            query = {"select": select, **(filters or {})}
            result, _ = self._request(
                f"/rest/v1/{table}",
                query=query,
                headers={"Range": f"{offset}-{offset + page_size - 1}", "Prefer": "count=exact"},
                optional=optional,
            )
            page = result if isinstance(result, list) else []
            rows.extend(row for row in page if isinstance(row, dict))
            if len(page) < page_size:
                break
            offset += page_size
            if offset >= 50_000:
                self.warnings.append(f"Stopped {table} import after 50,000 rows.")
                break
        return rows

    def rows_for_ids(
        self,
        table: str,
        field: str,
        ids: list[str],
        *,
        optional: bool = False,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for group in _chunks(ids):
            rows.extend(
                self.table_rows(
                    table,
                    filters={field: f"in.({','.join(group)})"},
                    optional=optional,
                )
            )
        return rows


def fetch_roomflow_supabase_dataset(client: RoomFlowSupabaseClient) -> dict[str, Any]:
    memberships = client.table_rows(
        "organization_members",
        filters={"user_id": f"eq.{client.user_id}"},
        select="organization_id,role_id",
        optional=True,
    )
    organization_ids = sorted({_text(row.get("organization_id"), 100) for row in memberships if row.get("organization_id")})
    organizations: list[dict[str, Any]] = []
    if organization_ids:
        organizations = client.rows_for_ids("organizations", "id", organization_ids, optional=True)
    else:
        # Some older RoomFlow policies expose organizations directly without a
        # membership row. RLS still limits this query to the signed-in account.
        organizations = client.table_rows("organizations", optional=True)
        organization_ids = sorted({_text(row.get("id"), 100) for row in organizations if row.get("id")})
    if not organization_ids:
        raise RoomFlowSupabaseError("No RoomFlow company was available to this Supabase login.")

    dataset: dict[str, Any] = {
        "source_user_id": client.user_id,
        "organizations": organizations,
        "memberships": memberships,
        "customers": [],
        "jobs": [],
        "catalog_items": [],
        "estimates": [],
        "estimate_lines": [],
        "project_snapshots": [],
        "layout_snapshots": [],
        "costing_snapshots": [],
        "legacy_pricing": [],
        "warnings": client.warnings,
    }
    for organization_id in organization_ids:
        org_filter = {"organization_id": f"eq.{organization_id}"}
        dataset["customers"].extend(client.table_rows("customers", filters=org_filter, optional=True))
        dataset["jobs"].extend(client.table_rows("jobs", filters=org_filter, optional=True))
        dataset["catalog_items"].extend(client.table_rows("estimate_catalog_items", filters=org_filter, optional=True))
        dataset["estimates"].extend(client.table_rows("estimates", filters=org_filter, optional=True))
        dataset["project_snapshots"].extend(client.table_rows("job_project_snapshots", filters=org_filter, optional=True))
        dataset["costing_snapshots"].extend(client.table_rows("job_costing_snapshots", filters=org_filter, optional=True))

    job_ids = [_text(row.get("id"), 100) for row in dataset["jobs"] if row.get("id")]
    estimate_ids = [_text(row.get("id"), 100) for row in dataset["estimates"] if row.get("id")]
    if job_ids:
        dataset["layout_snapshots"].extend(client.rows_for_ids("job_layouts", "job_id", job_ids, optional=True))
        dataset["legacy_pricing"].extend(client.rows_for_ids("job_pricing", "job_id", job_ids, optional=True))
        # Older installs can lack organization_id on the snapshot tables.
        existing_project_ids = {_text(row.get("job_id"), 100) for row in dataset["project_snapshots"]}
        missing_job_ids = [job_id for job_id in job_ids if job_id not in existing_project_ids]
        if missing_job_ids:
            dataset["project_snapshots"].extend(client.rows_for_ids("job_project_snapshots", "job_id", missing_job_ids, optional=True))
        existing_cost_ids = {_text(row.get("job_id"), 100) for row in dataset["costing_snapshots"]}
        missing_cost_ids = [job_id for job_id in job_ids if job_id not in existing_cost_ids]
        if missing_cost_ids:
            dataset["costing_snapshots"].extend(client.rows_for_ids("job_costing_snapshots", "job_id", missing_cost_ids, optional=True))
    if estimate_ids:
        dataset["estimate_lines"].extend(client.rows_for_ids("estimate_lines", "estimate_id", estimate_ids, optional=True))
    dataset["warnings"] = list(dict.fromkeys(client.warnings))
    return dataset


def _existing_contact_id(store: OfficeStore, source: dict[str, Any]) -> str:
    source_id = _text(source.get("id"), 100)
    email = _text(source.get("email"), 320).lower()
    phone = _text(source.get("phone"), 80)
    for record in store.records("contacts"):
        if source_id and source_id in {
            _text(record.get("roomflow_source_id"), 100),
            _text(record.get("external_id"), 100),
        }:
            return str(record["id"])
    matched = store.find_contact(email=email, phone=phone)
    return str(matched["id"]) if matched else _stable_id("contact", source_id or email or phone or str(uuid.uuid4()))


def _existing_property_id(store: OfficeStore, contact_id: str, source_job_id: str, address: str) -> str:
    normalized = address.casefold().strip()
    for record in store.records("properties"):
        if source_job_id and _text(record.get("roomflow_job_source_id"), 100) == source_job_id:
            return str(record["id"])
        candidate = _address(record).casefold().strip()
        if normalized and candidate == normalized and str(record.get("contact_id") or "") == contact_id:
            return str(record["id"])
    return _stable_id("property", source_job_id or f"{contact_id}:{normalized}")


def _existing_catalog_id(store: OfficeStore, source: dict[str, Any]) -> str:
    source_id = _text(source.get("id"), 100)
    name = _text(source.get("name"), 300).casefold()
    category = _text(source.get("category") or "General Services", 160).casefold()
    unit = _text(source.get("unit") or source.get("usage_unit") or "each", 80).casefold()
    for record in store.records("catalog_items"):
        if source_id and _text(record.get("roomflow_source_id"), 100) == source_id:
            return str(record["id"])
        if (
            _text(record.get("name"), 300).casefold() == name
            and _text(record.get("category") or "General Services", 160).casefold() == category
            and _text(record.get("unit") or "each", 80).casefold() == unit
        ):
            return str(record["id"])
    return _stable_id("catalog", source_id or f"{category}:{unit}:{name}")


def import_roomflow_dataset(
    store: OfficeStore,
    dataset: dict[str, Any],
    *,
    actor_id: str,
    run_id: str,
) -> dict[str, Any]:
    organizations = [row for row in dataset.get("organizations", []) if isinstance(row, dict)]
    memberships = [row for row in dataset.get("memberships", []) if isinstance(row, dict)]
    customers = [row for row in dataset.get("customers", []) if isinstance(row, dict)]
    jobs = [row for row in dataset.get("jobs", []) if isinstance(row, dict)]
    catalog_rows = [row for row in dataset.get("catalog_items", []) if isinstance(row, dict)]
    estimates = [row for row in dataset.get("estimates", []) if isinstance(row, dict)]
    estimate_lines = [row for row in dataset.get("estimate_lines", []) if isinstance(row, dict)]
    project_snapshots = [row for row in dataset.get("project_snapshots", []) if isinstance(row, dict)]
    layout_snapshots = [row for row in dataset.get("layout_snapshots", []) if isinstance(row, dict)]
    costing_snapshots = [row for row in dataset.get("costing_snapshots", []) if isinstance(row, dict)]
    legacy_pricing = [row for row in dataset.get("legacy_pricing", []) if isinstance(row, dict)]

    membership_by_org = {
        _text(row.get("organization_id"), 160): row
        for row in memberships
        if row.get("organization_id")
    }
    organization_by_source = {
        _text(row.get("id"), 160): row
        for row in organizations
        if row.get("id")
    }
    # Jobs and older customer/catalog rows can expose an organization even when
    # the organizations table is partially hidden by an old RLS policy.
    all_source_org_ids = {
        _text(row.get("organization_id"), 160)
        for row in [*organizations, *customers, *jobs, *catalog_rows, *estimates]
        if row.get("organization_id")
    }
    workspace_id_by_source: dict[str, str] = {}
    workspace_records: list[dict[str, Any]] = []
    existing_workspace_by_source = {
        _text(record.get("roomflow_organization_id") or record.get("source_organization_id"), 160): record
        for record in store.records("roomflow_workspaces")
        if record.get("roomflow_organization_id") or record.get("source_organization_id")
    }
    for source_org_id in sorted(all_source_org_ids):
        source_org = organization_by_source.get(source_org_id) or {}
        membership = membership_by_org.get(source_org_id) or {}
        existing = existing_workspace_by_source.get(source_org_id) or {}
        local_workspace_id = str(existing.get("id") or _workspace_id(source_org_id))
        workspace_id_by_source[source_org_id] = local_workspace_id
        workspace_records.append({
            "id": local_workspace_id,
            "name": _text(source_org.get("name") or source_org.get("company_name") or existing.get("name"), 300)
                or f"Imported RoomFlow company {source_org_id[:8]}",
            "timezone": _text(source_org.get("timezone") or existing.get("timezone"), 80)
                or _text(store.profile().get("timezone"), 80) or "America/Detroit",
            "status": "ACTIVE",
            "imported": True,
            "is_default": bool(existing.get("is_default", False)),
            "roomflow_organization_id": source_org_id,
            "source_organization_id": source_org_id,
            "membership_role_id": _text(membership.get("role_id"), 160) or None,
            "source_user_id": _text(dataset.get("source_user_id"), 160) or None,
            "organization_profile": deepcopy(source_org),
            "source": _SOURCE,
            "source_created_at": source_org.get("created_at"),
            "source_updated_at": source_org.get("updated_at"),
            "import_run_id": run_id,
        })

    contact_id_by_source: dict[str, str] = {}
    contact_records: list[dict[str, Any]] = []
    for row in customers:
        source_id = _text(row.get("id"), 100)
        if not source_id:
            continue
        local_id = _existing_contact_id(store, row)
        contact_id_by_source[source_id] = local_id
        name = _text(row.get("name") or row.get("full_name"), 300)
        first_name = _text(row.get("first_name"), 160)
        last_name = _text(row.get("last_name"), 160)
        if not first_name and name:
            parts = name.split(None, 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""
        existing_contact = store.record("contacts", local_id) or {}
        contact_record: dict[str, Any] = {
            "id": local_id,
            "name": name or _text(existing_contact.get("name"), 300) or "RoomFlow Customer",
            "status": "CUSTOMER",
            "roomflow_source_id": source_id,
            "roomflow_organization_id": _text(row.get("organization_id"), 100),
            "workspace_id": workspace_id_by_source.get(_text(row.get("organization_id"), 160)),
            "roomflow_organization_name": _text((organization_by_source.get(_text(row.get("organization_id"), 160)) or {}).get("name"), 300),
            "external_id": source_id,
            "source": _SOURCE,
            "source_created_at": row.get("created_at"),
            "source_updated_at": row.get("updated_at"),
        }
        incoming_contact_values = {
            "first_name": first_name,
            "last_name": last_name,
            "company": _text(row.get("company"), 240),
            "email": _text(row.get("email"), 320).lower(),
            "phone": _text(row.get("phone"), 80),
            "mailing_street": _text(row.get("address"), 300),
            "mailing_city": _text(row.get("city"), 160),
            "mailing_state": _text(row.get("state"), 80),
            "mailing_postal_code": _text(row.get("postal_code"), 40),
            "address": _address(row),
            "notes": _text(row.get("notes"), 12_000),
            "lead_source": _text(row.get("lead_source"), 200),
        }
        for key, value in incoming_contact_values.items():
            if value not in (None, ""):
                contact_record[key] = value
        if not contact_record.get("lead_source") and not existing_contact.get("lead_source"):
            contact_record["lead_source"] = "Original RoomFlow"
        contact_records.append(contact_record)

    job_by_source = {_text(row.get("id"), 100): row for row in jobs if row.get("id")}
    job_local_id: dict[str, str] = {}
    property_id_by_job: dict[str, str] = {}
    property_records: list[dict[str, Any]] = []
    for source_job_id, row in job_by_source.items():
        customer_source_id = _text(row.get("customer_id"), 100)
        contact_id = contact_id_by_source.get(customer_source_id)
        if not contact_id:
            # A job can remain accessible even when an older RLS policy hides
            # its customer row. Preserve it under a deterministic client file.
            contact_id = _stable_id("contact", f"job-customer:{source_job_id}")
            contact_id_by_source[customer_source_id or f"job:{source_job_id}"] = contact_id
            contact_records.append({
                "id": contact_id,
                "name": _text(row.get("name"), 300) or "Imported RoomFlow Customer",
                "first_name": "Imported",
                "last_name": "RoomFlow Customer",
                "status": "CUSTOMER",
                "lead_source": "Original RoomFlow",
                "roomflow_source_id": customer_source_id or None,
                "roomflow_organization_id": _text(row.get("organization_id"), 160) or None,
                "workspace_id": workspace_id_by_source.get(_text(row.get("organization_id"), 160)),
                "source": _SOURCE,
            })
        address = _address(row)
        property_id = _existing_property_id(store, contact_id, source_job_id, address)
        property_id_by_job[source_job_id] = property_id
        existing_property = store.record("properties", property_id) or {}
        property_name = _text(row.get("name"), 240) or _text(existing_property.get("property_name") or existing_property.get("name"), 240) or "RoomFlow Service Property"
        property_record: dict[str, Any] = {
            "id": property_id,
            "contact_id": contact_id,
            "name": property_name,
            "property_name": property_name,
            "property_type": _text(existing_property.get("property_type"), 80) or "SERVICE_PROPERTY",
            "roomflow_job_source_id": source_job_id,
            "roomflow_organization_id": _text(row.get("organization_id"), 100),
            "workspace_id": workspace_id_by_source.get(_text(row.get("organization_id"), 160)),
            "source": _SOURCE,
        }
        incoming_property_values = {
            "service_street": _text(row.get("property_address") or row.get("address"), 300),
            "service_city": _text(row.get("city"), 160),
            "service_state": _text(row.get("state"), 80),
            "service_postal_code": _text(row.get("postal_code"), 40),
            "service_address": address,
            "full_address": address,
            "notes": _text(row.get("issue_description"), 5_000),
        }
        for key, value in incoming_property_values.items():
            if value not in (None, ""):
                property_record[key] = value
        property_records.append(property_record)
        existing_job_id = ""
        for existing in store.records("roomflow_jobs"):
            if source_job_id in {
                _text(existing.get("roomflow_source_id"), 100),
                _text(existing.get("roomflow_job_id"), 100),
            }:
                existing_job_id = str(existing["id"])
                break
        job_local_id[source_job_id] = existing_job_id or _stable_id("job", source_job_id)

    catalog_id_by_source: dict[str, str] = {}
    catalog_records: list[dict[str, Any]] = []
    for row in catalog_rows:
        source_id = _text(row.get("id"), 100)
        if not source_id:
            continue
        local_id = _existing_catalog_id(store, row)
        catalog_id_by_source[source_id] = local_id
        price_cents = _cents(row, "unit_price_cents", "unit_price")
        catalog_records.append({
            "id": local_id,
            "name": _text(row.get("name"), 300) or "Imported RoomFlow item",
            "description": _text(row.get("description") or row.get("notes"), 8_000),
            "category": _text(row.get("category") or "General Services", 160),
            "unit": _text(row.get("unit") or row.get("usage_unit") or "each", 80),
            "unit_price_cents": price_cents,
            "unit_price": price_cents / 100,
            "taxable": bool(row.get("taxable")),
            "active": bool(row.get("active", True)),
            "pricing_method": _text(row.get("pricing_method") or "fixed", 80),
            "external_key": _text(row.get("external_key") or source_id, 300),
            "roomflow_source_id": source_id,
            "roomflow_organization_id": _text(row.get("organization_id"), 100),
            "workspace_id": workspace_id_by_source.get(_text(row.get("organization_id"), 160)),
            "source_provider": _SOURCE,
            "source": _SOURCE,
        })

    lines_by_estimate: dict[str, list[dict[str, Any]]] = {}
    for line in estimate_lines:
        estimate_source_id = _text(line.get("estimate_id"), 100)
        if estimate_source_id:
            lines_by_estimate.setdefault(estimate_source_id, []).append(line)
    for lines in lines_by_estimate.values():
        lines.sort(key=lambda item: (_int(item.get("sort_order")), _text(item.get("created_at"), 100)))

    estimate_local_id: dict[str, str] = {}
    estimate_records: list[dict[str, Any]] = []
    latest_estimate_for_job: dict[str, dict[str, Any]] = {}
    existing_estimates = store.records("estimates")
    for row in estimates:
        source_id = _text(row.get("id"), 100)
        source_job_id = _text(row.get("job_id"), 100)
        if not source_id or not source_job_id:
            continue
        number = _text(row.get("estimate_number"), 120)
        existing_id = ""
        for existing in existing_estimates:
            if source_id == _text(existing.get("roomflow_source_id"), 100):
                existing_id = str(existing["id"])
                break
            if number and number == _text(existing.get("estimate_number"), 120):
                existing_id = str(existing["id"])
                break
        local_id = existing_id or _stable_id("estimate", source_id)
        estimate_local_id[source_id] = local_id
        source_lines = lines_by_estimate.get(source_id, [])
        grouped: dict[str, dict[str, Any]] = {}
        section_order: list[str] = []
        line_records: list[dict[str, Any]] = []
        total_from_lines = 0
        for index, line in enumerate(source_lines):
            section_title = _text(line.get("section_name") or line.get("category") or "Scope of Work", 240)
            if section_title not in grouped:
                grouped[section_title] = {
                    "id": _stable_id("estimate-section", f"{source_id}:{section_title}"),
                    "title": section_title,
                    "description": "Imported from the original RoomFlow estimate.",
                    "sort_order": len(section_order),
                    "subtotal_cents": 0,
                }
                section_order.append(section_title)
            quantity = max(0.0, _float(line.get("quantity"), 0.0))
            price_cents = _cents(line, "unit_price_cents", "unit_price")
            line_total = int(round(quantity * price_cents))
            grouped[section_title]["subtotal_cents"] += line_total if line.get("selected", True) and not line.get("optional", False) else 0
            total_from_lines += line_total if line.get("selected", True) and not line.get("optional", False) else 0
            source_catalog_id = _text(line.get("catalog_item_id"), 100)
            line_records.append({
                "id": _stable_id("estimate-line", _text(line.get("id"), 100) or f"{source_id}:{index}"),
                "section_id": grouped[section_title]["id"],
                "section_name": section_title,
                "catalog_item_id": catalog_id_by_source.get(source_catalog_id),
                "roomflow_line_id": _text(line.get("roomflow_line_id"), 160) or None,
                "name": _text(line.get("name"), 300) or "Imported RoomFlow item",
                "description": _text(line.get("description"), 8_000),
                "category": _text(line.get("category") or "General Services", 160),
                "unit": _text(line.get("unit") or "each", 80),
                "quantity": quantity,
                "unit_price_cents": price_cents,
                "unit_price": price_cents / 100,
                "line_total_cents": line_total,
                "taxable": bool(line.get("taxable")),
                "optional": bool(line.get("optional")),
                "selected": bool(line.get("selected", True)),
                "sort_order": _int(line.get("sort_order"), index),
                "pricing_method": _text(line.get("pricing_method") or "fixed", 80),
                "calculation_metadata": line.get("calculation_metadata") if isinstance(line.get("calculation_metadata"), dict) else {},
            })
        total_cents = _cents(row, "total_cents", "total", total_from_lines)
        if not total_cents:
            total_cents = total_from_lines
        source_job = job_by_source.get(source_job_id, {})
        category = _infer_project_category(source_job, source_lines)
        contact_id = contact_id_by_source.get(_text(source_job.get("customer_id"), 100))
        property_id = property_id_by_job.get(source_job_id)
        base = {
            "id": local_id,
            "estimate_number": number or f"RF-{source_id[:8].upper()}",
            "contact_id": contact_id,
            "property_id": property_id,
            "title": _text(row.get("title") or source_job.get("name") or "RoomFlow Estimate", 300),
            "project_category": category,
            "status": _status(row.get("status")),
            "currency": _text(row.get("currency") or "USD", 12),
            "sections": [grouped[title] for title in section_order],
            "line_items": line_records,
            "total_cents": total_cents,
            "subtotal_cents": _cents(row, "subtotal_cents", "subtotal", total_from_lines),
            "taxable_subtotal_cents": _cents(row, "taxable_subtotal_cents", "taxable_subtotal"),
            "tax_rate": _float(row.get("tax_rate"), 0.0),
            "tax_total_cents": _cents(row, "tax_total_cents", "tax_total"),
            "terms": _text(row.get("terms"), 12_000),
            "deposit_type": "PERCENT",
            "deposit_percent": 50.0,
            "deposit_cents": int(round(total_cents * 0.5)),
            "deposit_balance_cents": int(round(total_cents * 0.5)),
            "deposit_paid_cents": 0,
            "deposit_due_stage": "AFTER_AUTHORIZATION",
            "roomflow_job_id": job_local_id.get(source_job_id),
            "roomflow_source_id": source_id,
            "roomflow_job_source_id": source_job_id,
            "roomflow_organization_id": _text(source_job.get("organization_id"), 160),
            "workspace_id": workspace_id_by_source.get(_text(source_job.get("organization_id"), 160)),
            "source": _SOURCE,
            "source_created_at": row.get("created_at"),
            "source_updated_at": row.get("updated_at"),
        }
        estimate_record = merge_project_plan(base)
        estimate_records.append(estimate_record)
        version_key = (
            _int(row.get("version_number"), 0),
            _text(row.get("updated_at") or row.get("created_at"), 100),
        )
        current = latest_estimate_for_job.get(source_job_id)
        if current is None or version_key > current["sort_key"]:
            latest_estimate_for_job[source_job_id] = {"sort_key": version_key, "record": estimate_record}

    project_by_job: dict[str, dict[str, Any]] = {}
    for row in project_snapshots:
        source_job_id = _text(row.get("job_id"), 100)
        if not source_job_id:
            continue
        candidate = row.get("project_state") if isinstance(row.get("project_state"), dict) else {}
        current = project_by_job.get(source_job_id)
        stamp = _text(row.get("client_updated_at") or row.get("updated_at"), 100)
        if current is None or stamp >= current["stamp"]:
            project_by_job[source_job_id] = {"stamp": stamp, "value": candidate}
    layout_by_job: dict[str, dict[str, Any]] = {}
    for row in layout_snapshots:
        source_job_id = _text(row.get("job_id"), 100)
        if not source_job_id:
            continue
        candidate = row.get("layout_json") if isinstance(row.get("layout_json"), dict) else {}
        version = _int(row.get("version_number"), 0)
        current = layout_by_job.get(source_job_id)
        if current is None or version >= current["version"]:
            layout_by_job[source_job_id] = {"version": version, "value": candidate}
    costing_by_job: dict[str, dict[str, Any]] = {}
    for row in costing_snapshots:
        source_job_id = _text(row.get("job_id"), 100)
        if not source_job_id:
            continue
        candidate = row.get("costing_state") if isinstance(row.get("costing_state"), dict) else {}
        stamp = _text(row.get("client_updated_at") or row.get("updated_at"), 100)
        current = costing_by_job.get(source_job_id)
        if current is None or stamp >= current["stamp"]:
            costing_by_job[source_job_id] = {"stamp": stamp, "value": candidate}

    legacy_pricing_by_job = {
        _text(row.get("job_id"), 100): row
        for row in legacy_pricing
        if row.get("job_id")
    }

    roomflow_records: list[dict[str, Any]] = []
    for source_job_id, row in job_by_source.items():
        local_job_id = job_local_id[source_job_id]
        source_customer_id = _text(row.get("customer_id"), 100)
        contact_id = contact_id_by_source.get(source_customer_id)
        property_id = property_id_by_job.get(source_job_id)
        latest = latest_estimate_for_job.get(source_job_id, {}).get("record")
        snapshot = deepcopy(project_by_job.get(source_job_id, {}).get("value") or layout_by_job.get(source_job_id, {}).get("value") or {})
        if not isinstance(snapshot, dict):
            snapshot = {}
        costing = deepcopy(costing_by_job.get(source_job_id, {}).get("value") or snapshot.get("costing") or {})
        if not isinstance(costing, dict):
            costing = {}
        legacy = legacy_pricing_by_job.get(source_job_id) or {}
        settings = costing.get("settings") if isinstance(costing.get("settings"), dict) else {}
        settings.setdefault("targetGrossMargin", _float(legacy.get("target_gross_margin"), 40.0))
        settings.setdefault("salesTaxRate", _float(legacy.get("sales_tax_rate"), 6.0))
        settings.setdefault("overhead", _float(legacy.get("additional_overhead_rate"), 15.0))
        costing["settings"] = settings
        costing.setdefault("commission", _float(legacy.get("commission_rate"), 0.0))
        contact = next((item for item in contact_records if item["id"] == contact_id), {})
        prop = next((item for item in property_records if item["id"] == property_id), {})
        costing.setdefault("customerName", _text(contact.get("name") or row.get("name"), 300))
        costing.setdefault("customerEmail", _text(contact.get("email"), 320))
        costing.setdefault("customerPhone", _text(contact.get("phone"), 80))
        costing.setdefault("customerAddress", _text(prop.get("full_address") or _address(row), 500))
        costing.setdefault("serviceStreet", _text(prop.get("service_street"), 300))
        costing.setdefault("serviceCity", _text(prop.get("service_city"), 160))
        costing.setdefault("serviceState", _text(prop.get("service_state"), 80))
        costing.setdefault("servicePostalCode", _text(prop.get("service_postal_code"), 40))
        if latest and not costing.get("customItems"):
            costing["customItems"] = [
                {
                    "roomflowLineId": line.get("roomflow_line_id") or line.get("id"),
                    "catalogItemId": line.get("catalog_item_id"),
                    "sectionName": line.get("section_name") or "Scope of Work",
                    "header": line.get("section_name") or "Scope of Work",
                    "name": line.get("name"),
                    "description": line.get("description"),
                    "category": line.get("category"),
                    "unit": line.get("unit"),
                    "qty": line.get("quantity"),
                    "quantity": line.get("quantity"),
                    "unitCost": (line.get("unit_price_cents") or 0) / 100,
                    "unit_price": (line.get("unit_price_cents") or 0) / 100,
                    "taxable": line.get("taxable", False),
                    "optional": line.get("optional", False),
                }
                for line in latest.get("line_items", [])
            ]
            costing.setdefault("estimateHeader", latest.get("title") or row.get("name") or "RoomFlow Estimate")
            costing.setdefault("projectCategory", latest.get("project_category") or "general-restoration")
        snapshot["costing"] = costing
        snapshot["jobId"] = local_job_id
        snapshot["roomflowSourceJobId"] = source_job_id
        source_workspace_id = workspace_id_by_source.get(_text(row.get("organization_id"), 160))
        snapshot["workspaceId"] = source_workspace_id
        snapshot["organizationId"] = source_workspace_id
        snapshot["currentOrganization"] = workspace_public(next((workspace for workspace in workspace_records if workspace.get("id") == source_workspace_id), {}))
        snapshot["currentJobName"] = _text(row.get("name"), 300) or "Imported RoomFlow Job"
        snapshot["customerName"] = costing.get("customerName")
        snapshot["customerAddress"] = costing.get("customerAddress")
        snapshot["sharedFromCloud"] = True
        snapshot["syncState"] = "synchronized"
        arrays = ("rooms", "levels", "capturedMeasurements", "walls", "doors", "windows", "sumpPumps", "dehumidifiers")
        summary = {name: len(snapshot.get(name) or []) if isinstance(snapshot.get(name), list) else 0 for name in arrays}
        roomflow_records.append({
            "id": local_job_id,
            "roomflow_job_id": source_job_id,
            "roomflow_source_id": source_job_id,
            "roomflow_organization_id": _text(row.get("organization_id"), 100),
            "workspace_id": workspace_id_by_source.get(_text(row.get("organization_id"), 160)),
            "roomflow_organization_name": _text((organization_by_source.get(_text(row.get("organization_id"), 160)) or {}).get("name"), 300),
            "job_name": _text(row.get("name"), 300) or "Imported RoomFlow Job",
            "name": _text(row.get("name"), 300) or "Imported RoomFlow Job",
            "contact_id": contact_id,
            "property_id": property_id,
            "estimate_id": latest.get("id") if latest else None,
            "estimate_number": latest.get("estimate_number") if latest else "",
            "status": _status(row.get("status")),
            "project_category": latest.get("project_category") if latest else _infer_project_category(row, []),
            "customer_name": costing.get("customerName") or _text(row.get("name"), 300),
            "property_address": costing.get("customerAddress") or _address(row),
            "snapshot": snapshot,
            "summary": summary,
            "sections": [
                {
                    "title": section.get("title") or "Scope of Work",
                    "description": section.get("description") or "",
                    "lines": [line for line in latest.get("line_items", []) if line.get("section_id") == section.get("id")],
                }
                for section in (latest.get("sections", []) if latest else [])
            ],
            "layout_capture_required": True,
            "layout_available": False,
            "source": _SOURCE,
            "source_created_at": row.get("created_at"),
            "source_updated_at": row.get("updated_at"),
            "import_run_id": run_id,
        })

    bulk = store.bulk_upsert_records(
        {
            "roomflow_workspaces": workspace_records,
            "contacts": contact_records,
            "properties": property_records,
            "catalog_items": catalog_records,
            "estimates": estimate_records,
            "roomflow_jobs": roomflow_records,
        },
        actor_id=actor_id,
    )
    selected_workspace_id = ""
    if workspace_records:
        selected_workspace_id = selected_roomflow_workspace_id(
            store,
            actor_id,
            preferred_workspace_id=str(workspace_records[0]["id"]),
            actor_id=actor_id,
        )
    else:
        selected_workspace_id = selected_roomflow_workspace_id(store, actor_id, actor_id=actor_id)

    counts = {
        "organizations": len(workspace_records),
        "workspaces": len(workspace_records),
        "customers": len(contact_records),
        "properties": len(property_records),
        "jobs": len(roomflow_records),
        "catalog_items": len(catalog_records),
        "estimates": len(estimate_records),
        "estimate_lines": sum(len(record.get("line_items") or []) for record in estimate_records),
    }
    return {
        "status": "COMPLETED",
        "run_id": run_id,
        "counts": counts,
        "writes": bulk,
        "warnings": list(dict.fromkeys(dataset.get("warnings") or [])),
        "layout_capture_required": sum(1 for record in roomflow_records if record.get("layout_capture_required")),
        "selected_workspace_id": selected_workspace_id,
        "workspaces": [workspace_public(record) for record in ensure_roomflow_workspaces(store, actor_id=actor_id)],
    }


def import_roomflow_supabase(
    store: OfficeStore,
    *,
    email: str,
    password: str,
    actor_id: str,
    supabase_url: str = DEFAULT_ROOMFLOW_SUPABASE_URL,
    supabase_anon_key: str = DEFAULT_ROOMFLOW_SUPABASE_ANON_KEY,
) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    email_key = email.strip().lower()
    email_hash = hashlib.sha256(email_key.encode("utf-8")).hexdigest()
    store.create_record(
        "roomflow_imports",
        {
            "id": run_id,
            "status": "RUNNING",
            "email_hash": email_hash,
            "email_hint": (email_key[:2] + "***@" + email_key.split("@", 1)[1]) if "@" in email_key else "hidden",
            "started_at": _now_iso(),
            "source": _SOURCE,
        },
        actor_id=actor_id,
    )
    try:
        client = RoomFlowSupabaseClient(supabase_url, supabase_anon_key)
        client.sign_in(email_key, password)
        dataset = fetch_roomflow_supabase_dataset(client)
        result = import_roomflow_dataset(store, dataset, actor_id=actor_id, run_id=run_id)
        store.update_record(
            "roomflow_imports",
            run_id,
            {
                **result,
                "completed_at": _now_iso(),
                "source_user_id": dataset.get("source_user_id"),
            },
            actor_id=actor_id,
        )
        return result
    except Exception as exc:
        message = str(exc)[:1_000] or "RoomFlow Supabase import failed."
        store.update_record(
            "roomflow_imports",
            run_id,
            {"status": "FAILED", "error": message, "completed_at": _now_iso()},
            actor_id=actor_id,
        )
        if isinstance(exc, RoomFlowSupabaseError):
            raise
        raise RoomFlowSupabaseError(message) from exc
