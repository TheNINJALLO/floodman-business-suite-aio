from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from app.roomflow_supabase import import_roomflow_dataset, import_roomflow_supabase
from app.store import OfficeStore


def dataset(*, updated: bool = False, with_legacy_layout: bool = False):
    org = "11111111-1111-4111-8111-111111111111"
    customer = "22222222-2222-4222-8222-222222222222"
    job = "33333333-3333-4333-8333-333333333333"
    catalog = "44444444-4444-4444-8444-444444444444"
    estimate = "55555555-5555-4555-8555-555555555555"
    return {
        "source_user_id": "99999999-9999-4999-8999-999999999999",
        "organizations": [{"id": org, "name": "Floodman Original RoomFlow", "timezone": "America/Detroit"}],
        "memberships": [{"organization_id": org, "role_id": "owner-role"}],
        "customers": [{
            "id": customer, "organization_id": org, "name": "Alex Carter Updated" if updated else "Alex Carter",
            "email": "alex@example.com", "phone": "2315550148", "address": "1847 Pine Ridge Lane",
            "city": "Traverse City", "state": "MI", "postal_code": "49686",
        }],
        "jobs": [{
            "id": job, "organization_id": org, "customer_id": customer,
            "name": "Carter Basement Updated" if updated else "Carter Basement", "status": "Draft", "property_address": "1847 Pine Ridge Lane",
            "city": "Traverse City", "state": "MI", "postal_code": "49686",
            "issue_description": "Basement waterproofing and sump drainage",
        }],
        "catalog_items": [{
            "id": catalog, "organization_id": org, "name": "Interior perimeter drainage",
            "category": "Moisture control and drainage", "unit": "LF", "unit_price": 45.00,
            "taxable": False, "active": True,
        }],
        "estimates": [{
            "id": estimate, "organization_id": org, "job_id": job, "status": "draft",
            "estimate_number": "RF-2026-0148", "version_number": 1, "total": 4140.00,
        }],
        "estimate_lines": [{
            "id": "66666666-6666-4666-8666-666666666666", "estimate_id": estimate,
            "catalog_item_id": catalog, "section_name": "Moisture control and drainage",
            "category": "waterproofing", "name": "Interior perimeter drainage",
            "quantity": 96 if updated else 92, "unit": "LF", "unit_price": 45.00, "taxable": False,
            "selected": True, "optional": False, "sort_order": 0,
        }],
        "project_snapshots": [{
            "job_id": job, "project_state": {
                "rooms": [{"id": "room-1", "name": "Basement", "w": 20, "l": 30}],
                "walls": [], "levels": [{"id": "basement", "name": "Basement"}],
            },
            "client_updated_at": "2026-08-10T12:00:00Z",
        }],
        "layout_snapshots": [{
            "job_id": job,
            "layout_json": {"rooms": [{"id": "layout-room", "name": "Imported measured basement", "w": 21, "l": 31}]},
            "version_number": 3,
        }] if with_legacy_layout else [],
        "costing_snapshots": [{
            "job_id": job, "costing_state": {"settings": {"salesTaxRate": 0}},
            "client_updated_at": "2026-08-10T12:00:00Z",
        }],
        "legacy_pricing": [{
            "job_id": job, "target_gross_margin": 42, "additional_overhead_rate": 16,
            "sales_tax_rate": 6, "commission_rate": 5,
        }],
        "warnings": [],
    }


class FakeResponse:
    def __init__(self, value):
        self.value = value
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.value).encode("utf-8")


def mocked_supabase_urlopen(source, requests):
    tables = {
        "organization_members": source["memberships"],
        "organizations": source["organizations"],
        "customers": source["customers"],
        "jobs": source["jobs"],
        "estimate_catalog_items": source["catalog_items"],
        "estimates": source["estimates"],
        "estimate_lines": source["estimate_lines"],
        "job_project_snapshots": source["project_snapshots"],
        "job_layouts": source["layout_snapshots"],
        "job_costing_snapshots": source["costing_snapshots"],
        "job_pricing": source["legacy_pricing"],
    }

    def responder(request, **_kwargs):
        requests.append(request)
        parsed = urlsplit(request.full_url)
        if parsed.path == "/auth/v1/token":
            body = json.loads((request.data or b"{}").decode("utf-8"))
            assert body == {"email": "owner@example.com", "password": "temporary-import-password"}
            return FakeResponse({"access_token": "test-user-access-token", "user": {"id": source["source_user_id"]}})
        assert request.get_header("Authorization") == "Bearer test-user-access-token"
        table = parsed.path.rsplit("/", 1)[-1]
        query = parse_qs(parsed.query)
        if table == "organization_members":
            assert query.get("user_id") == [f"eq.{source['source_user_id']}"]
        elif table in {"customers", "jobs", "estimate_catalog_items", "estimates", "job_project_snapshots", "job_costing_snapshots"}:
            if "organization_id" in query:
                assert query["organization_id"] == [f"eq.{source['organizations'][0]['id']}"]
            else:
                assert table in {"job_project_snapshots", "job_costing_snapshots"}
                assert query.get("job_id") == [f"in.({source['jobs'][0]['id']})"]
        return FakeResponse(tables.get(table, []))

    return responder


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = OfficeStore(str(Path(temp) / "office"))
        first = import_roomflow_dataset(store, dataset(), actor_id="owner", run_id="run-1")
        imported_contact = store.records("contacts")[0]
        store.update_record("contacts", imported_contact["id"], {"company": "Existing Floodman Client", "notes": "Keep this local note."}, actor_id="owner")
        second = import_roomflow_dataset(store, dataset(updated=True), actor_id="owner", run_id="run-2")
        assert first["counts"]["jobs"] == 1
        assert first["counts"]["workspaces"] == 1
        assert first["selected_workspace_id"]
        assert first["workspaces"][0]["name"] == "Floodman Original RoomFlow"
        assert first["workspaces"][0]["roomflow_organization_id"] == "11111111-1111-4111-8111-111111111111"
        assert len(store.records("contacts")) == 1
        assert store.records("contacts")[0]["company"] == "Existing Floodman Client"
        assert store.records("contacts")[0]["notes"] == "Keep this local note."
        assert len(store.records("properties")) == 1
        assert len(store.records("roomflow_jobs")) == 1
        assert len(store.records("catalog_items")) == 1
        assert len(store.records("estimates")) == 1
        job = store.records("roomflow_jobs")[0]
        assert job["name"] == "Carter Basement Updated"
        assert job["snapshot"]["rooms"][0]["name"] == "Basement"
        assert job["workspace_id"] == first["selected_workspace_id"]
        assert job["snapshot"]["workspaceId"] == first["selected_workspace_id"]
        assert store.records("contacts")[0]["workspace_id"] == first["selected_workspace_id"]
        assert store.records("properties")[0]["workspace_id"] == first["selected_workspace_id"]
        assert store.records("catalog_items")[0]["workspace_id"] == first["selected_workspace_id"]
        assert job["snapshot"]["costing"]["settings"]["targetGrossMargin"] == 42
        assert job["snapshot"]["costing"]["commission"] == 5
        assert job["layout_capture_required"] is True
        assert job["estimate_id"]
        estimate = store.record("estimates", job["estimate_id"])
        assert estimate and estimate["sections"][0]["title"] == "Moisture control and drainage"
        assert estimate["line_items"][0]["quantity"] == 96
        assert estimate["project_category"] == "basement-waterproofing"
        assert estimate["deposit_cents"] == 207000
        assert second["writes"]["roomflow_jobs"]["updated"] == 1

    with tempfile.TemporaryDirectory() as temp:
        store = OfficeStore(str(Path(temp) / "office"))
        source = dataset(with_legacy_layout=True)
        # Exercise the real auth/fetch/import entry point without a live account.
        source["project_snapshots"] = []
        requests = []
        with patch("app.roomflow_supabase.urlopen", side_effect=mocked_supabase_urlopen(source, requests)):
            result = import_roomflow_supabase(
                store,
                email="Owner@Example.com",
                password="temporary-import-password",
                actor_id="owner",
                supabase_url="https://roomflow.test",
                supabase_anon_key="public-anon-key",
            )
        assert result["counts"]["organizations"] == 1
        imported = store.records("roomflow_jobs")[0]
        assert imported["snapshot"]["rooms"][0]["name"] == "Imported measured basement"
        assert imported["snapshot"]["roomflowSourceJobId"] == source["jobs"][0]["id"]
        persisted = json.dumps(store.snapshot(), sort_keys=True)
        assert "temporary-import-password" not in persisted
        assert "test-user-access-token" not in persisted
        assert "owner@example.com" not in persisted
        assert any(urlsplit(request.full_url).path == "/auth/v1/token" for request in requests)
        assert any(urlsplit(request.full_url).path == "/rest/v1/estimate_lines" for request in requests)
        for table in ("customers", "jobs", "estimate_catalog_items", "estimates", "job_project_snapshots", "job_costing_snapshots"):
            assert any(
                urlsplit(request.full_url).path == f"/rest/v1/{table}"
                and parse_qs(urlsplit(request.full_url).query).get("organization_id") == [f"eq.{source['organizations'][0]['id']}"]
                for request in requests
            )
        print("RoomFlow Supabase import smoke test passed")


if __name__ == "__main__":
    main()
