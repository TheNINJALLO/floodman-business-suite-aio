from types import SimpleNamespace

from app.adapters.gauzy import GauzyClient


def client_stub() -> GauzyClient:
    client = GauzyClient.__new__(GauzyClient)
    client.settings = SimpleNamespace(
        gauzy_create_property_projects=True,
        gauzy_project_path="/organization-projects",
        gauzy_invoice_path="/invoices",
    )
    client._resolved_context = ("tenant-1", "org-1", "org-1")
    return client


def test_roomflow_project_code_is_stable_and_bounded() -> None:
    code = GauzyClient._property_project_code({"roomflow_job_id": "job-ca607b5c-c6a2-400e-99f2-cdda3b3055f3"})
    assert code.startswith("RF-")
    assert len(code) <= 27
    assert code == GauzyClient._property_project_code({"roomflow_job_id": "job-ca607b5c-c6a2-400e-99f2-cdda3b3055f3"})


def test_property_project_links_contact_and_address() -> None:
    client = client_stub()
    captured = {}
    client.find_property_project = lambda code: None

    def request(method, path, **kwargs):
        captured.update({"method": method, "path": path, "payload": kwargs.get("json")})
        return {"id": "project-1", **(kwargs.get("json") or {})}

    client._request = request
    result = client.ensure_property_project(
        {
            "roomflow_job_id": "RF-JOB-44",
            "currency": "USD",
            "customer": {"first_name": "Jane", "last_name": "Local"},
            "property": {
                "service_address": {
                    "street": "100 Main Street",
                    "city": "Detroit",
                    "state": "MI",
                    "postal_code": "48201",
                }
            },
        },
        contact_id="contact-1",
    )
    assert result["id"] == "project-1"
    assert captured["path"] == "/organization-projects/"
    assert captured["payload"]["organizationContactId"] == "contact-1"
    assert "100 Main Street" in captured["payload"]["name"]
    assert captured["payload"]["code"].startswith("RF-")


def test_estimate_line_items_are_attached_to_the_property_project() -> None:
    client = client_stub()
    calls = []
    client.find_estimate = lambda number: None

    def request(method, path, **kwargs):
        calls.append((method, path, kwargs.get("json")))
        if method == "POST" and path == "/invoices":
            return {"id": "estimate-1"}
        return {"ok": True}

    client._request = request
    job = {
        "invoice_number": 1001,
        "total_cents": 125000,
        "currency": "USD",
        "customer": {"first_name": "Jane", "last_name": "Local", "email": "jane@example.com"},
        "estimate": {
            "terms": "Due upon receipt",
            "internal_note": "RoomFlow",
            "discount_cents": 0,
            "tax_cents": 0,
            "payment_schedule": {"deposit_due_date": "2026-08-05"},
            "lines": [
                {
                    "description": "Drainage system",
                    "unit_price_cents": 125000,
                    "quantity": 1,
                    "line_total_cents": 125000,
                }
            ],
        },
    }
    result = client.create_estimate(job, "contact-1", "project-1")
    assert result["id"] == "estimate-1"
    bulk = next(payload for method, path, payload in calls if path == "/invoice-item/bulk/estimate-1")
    assert bulk["list"][0]["projectId"] == "project-1"
