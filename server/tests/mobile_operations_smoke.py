from __future__ import annotations

import base64
import os
import tempfile
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.mobile_api import build_mobile_router
from app.providers import ProviderClient
from app.store import OfficeStore


def run() -> None:
    root = tempfile.mkdtemp(prefix="floodman-v44-")
    signing = base64.b64encode(b"1" * 32).decode()
    os.environ.update({
        "OFFICE_CONSOLE_DATA_DIR": root,
        "DOCUMENTS_PATH": root + "/docs",
        "FLOODMAN_MOBILE_TOKEN_SECRET": "x" * 64,
        "FLOODMAN_MOBILE_API_PUBLIC_URL": "https://example.invalid/mobile-api",
        "FLOODMAN_CUSTOMER_PUBLIC_URL": "https://example.invalid/customer",
        "FLOODMAN_PAYMENTS_ENABLED": "false",
        "AR_TIMEZONE": "America/Detroit",
        "INTERNAL_HMAC_KEYS": "v1:" + signing,
        "AI_HMAC_KEYS": "v1:" + signing,
    })
    settings = Settings.from_env()
    store = OfficeStore(root)
    owner = store.create_owner("Josh Aldrich", "josh@floodman.com", "Password12345!")
    tech = owner
    app = FastAPI()
    app.include_router(build_mobile_router(store, ProviderClient(settings), settings))
    client = TestClient(app)
    login = client.post("/mobile-api/v1/auth/login", json={"email":"josh@floodman.com","password":"Password12345!","auth_source":"local","device_id":"android-v44-test","device_name":"Test","platform":"android","app_version":"0.2.0"})
    assert login.status_code == 200, login.text
    headers = {"Authorization":"Bearer "+login.json()["access_token"]}
    customer = client.post("/mobile-api/v1/customers", headers=headers, json={"first_name":"Alex","last_name":"Carter","email":"alex@example.com"}).json()
    prop = client.post("/mobile-api/v1/properties", headers=headers, json={"contact_id":customer["id"],"service_street":"1847 Pine Ridge Lane","service_city":"Traverse City","service_state":"MI","service_postal_code":"49686"}).json()
    plans = client.get("/mobile-api/v1/project-plans", headers=headers)
    assert plans.status_code == 200 and len(plans.json()["items"]) >= 8
    estimate = client.post("/mobile-api/v1/estimates", headers=headers, json={
        "contact_id":customer["id"],"property_id":prop["id"],"title":"Crawlspace project","project_category":"crawlspace-encapsulation",
        "sections":[{"title":"Encapsulation","lines":[{"name":"20 mil liner","quantity":1000,"unit":"sq ft","unit_price_cents":400}]}]
    })
    assert estimate.status_code == 200, estimate.text
    est=estimate.json()
    assert est["project_category"] == "crawlspace-encapsulation"
    assert est["recommended_project_title"]
    update = client.patch(f"/mobile-api/v1/estimates/{est['id']}", headers=headers, json={"sections":[
        {"title":"Waterproofing","description":"Drainage scope","lines":[{"name":"Drain system","quantity":92,"unit":"LF","unit_price_cents":4500}]},
        {"title":"Landfill Fees","lines":[{"name":"Disposal","quantity":1,"unit":"project","unit_price_cents":80000,"save_to_catalog":True}]}
    ]})
    assert update.status_code == 200, update.text
    assert len(update.json()["sections"]) == 2
    pdf = client.get(f"/mobile-api/v1/estimates/{est['id']}/pdf", headers=headers)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    accepted = client.post(f"/mobile-api/v1/estimates/{est['id']}/action", headers=headers, json={"action":"mark_accepted"})
    assert accepted.status_code == 200, accepted.text
    converted = client.post(f"/mobile-api/v1/estimates/{est['id']}/action", headers=headers, json={"action":"convert_to_invoice"})
    assert converted.status_code == 200, converted.text
    invoice = converted.json()["invoice"]
    inv_detail = client.get(f"/mobile-api/v1/invoices/{invoice['id']}", headers=headers)
    assert inv_detail.status_code == 200
    inv_pdf = client.get(f"/mobile-api/v1/invoices/{invoice['id']}/pdf", headers=headers)
    assert inv_pdf.status_code == 200 and inv_pdf.content.startswith(b"%PDF")
    start=datetime.now(UTC)+timedelta(days=1)
    end=start+timedelta(hours=2)
    appt = client.post("/mobile-api/v1/appointments", headers=headers, json={"title":"Crawlspace inspection","appointment_type":"INSPECTION","start_at":start.isoformat(),"end_at":end.isoformat(),"contact_id":customer["id"],"property_id":prop["id"],"assigned_user_ids":[tech["id"]],"lead_user_id":tech["id"]})
    assert appt.status_code == 200, appt.text
    conflict = client.post("/mobile-api/v1/appointments", headers=headers, json={"title":"Conflicting job","start_at":start.isoformat(),"end_at":end.isoformat(),"assigned_user_ids":[tech["id"]]})
    assert conflict.status_code == 409, conflict.text
    calendar = client.get("/mobile-api/v1/calendar", headers=headers)
    assert calendar.status_code == 200 and calendar.json()["items"]
    task = client.post("/mobile-api/v1/tasks", headers=headers, json={"title":"Prepare equipment","assigned_user_id":tech["id"],"appointment_id":appt.json()["appointment"]["id"]})
    assert task.status_code == 200, task.text
    print("Floodman v4.6 mobile operations smoke test passed")

if __name__ == "__main__":
    run()
