from __future__ import annotations

import tempfile
from pathlib import Path

from app.roomflow_supabase import import_roomflow_dataset
from app.store import OfficeStore


def dataset():
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
            "id": customer, "organization_id": org, "name": "Alex Carter",
            "email": "alex@example.com", "phone": "2315550148", "address": "1847 Pine Ridge Lane",
            "city": "Traverse City", "state": "MI", "postal_code": "49686",
        }],
        "jobs": [{
            "id": job, "organization_id": org, "customer_id": customer,
            "name": "Carter Basement", "status": "Draft", "property_address": "1847 Pine Ridge Lane",
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
            "quantity": 92, "unit": "LF", "unit_price": 45.00, "taxable": False,
            "selected": True, "optional": False, "sort_order": 0,
        }],
        "project_snapshots": [{
            "job_id": job, "project_state": {
                "rooms": [{"id": "room-1", "name": "Basement", "w": 20, "l": 30}],
                "walls": [], "levels": [{"id": "basement", "name": "Basement"}],
            },
            "client_updated_at": "2026-08-10T12:00:00Z",
        }],
        "layout_snapshots": [],
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


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = OfficeStore(str(Path(temp) / "office"))
        first = import_roomflow_dataset(store, dataset(), actor_id="owner", run_id="run-1")
        imported_contact = store.records("contacts")[0]
        store.update_record("contacts", imported_contact["id"], {"company": "Existing Floodman Client", "notes": "Keep this local note."}, actor_id="owner")
        second = import_roomflow_dataset(store, dataset(), actor_id="owner", run_id="run-2")
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
        assert estimate["line_items"][0]["quantity"] == 92
        assert estimate["project_category"] == "basement-waterproofing"
        assert estimate["deposit_cents"] == 207000
        assert second["writes"]["roomflow_jobs"]["updated"] == 1
        print("RoomFlow Supabase import smoke test passed")


if __name__ == "__main__":
    main()
