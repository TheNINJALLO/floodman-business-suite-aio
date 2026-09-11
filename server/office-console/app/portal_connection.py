from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from .roomflow_assets import layout_path

logger = logging.getLogger(__name__)


class PortalRequestError(RuntimeError):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"Photo portal returned HTTP {status_code}")


class PortalConnection:
    """Retryable synchronization of approved, locally committed call records."""

    def __init__(self, store: Any, providers: Any, settings: Any):
        self.store = store
        self.providers = providers
        self.settings = settings
        self.task: asyncio.Task | None = None

    @property
    def enabled(self) -> bool:
        url = urlsplit(self.settings.external_portal_api_url)
        return bool(url.scheme == "https" and url.hostname and not url.username and not url.password
                    and re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", url.netloc)
                    and not url.query and not url.fragment and len(self.settings.external_portal_api_token) >= 32)

    @property
    def origin(self) -> str:
        url = urlsplit(self.settings.external_portal_api_url)
        return f"{url.scheme}://{url.netloc}" if self.enabled else ""

    async def request(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("Photo portal connection needs setup")
        body = json.dumps({**payload, "action": action}, separators=(",", ":"), sort_keys=True).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(self.settings.external_portal_api_token.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await client.post(self.settings.external_portal_api_url, content=body,
                                        headers={"Content-Type": "application/json", "X-Floodman-Timestamp": timestamp, "X-Floodman-Signature": signature})
        if response.status_code != 200:
            raise PortalRequestError(response.status_code)
        result = response.json()
        if not isinstance(result, dict):
            raise RuntimeError("Photo portal returned an invalid response")
        return result

    def gallery_url(self, source_key: str) -> str:
        if not self.enabled or len(source_key) != 64 or any(char not in "0123456789abcdef" for char in source_key):
            return ""
        expires = int(time.time()) + 3600
        signature = hmac.new(self.settings.external_portal_api_token.encode(), f"gallery:{source_key}::{expires}".encode(), hashlib.sha256).hexdigest()
        return self.settings.external_portal_api_url + "?" + urlencode({"view": "gallery", "key": source_key, "expires": expires, "signature": signature})

    def gallery_html(self, document: dict[str, Any]) -> str:
        # The caller has already validated this estimate's private customer token.
        if not document.get("sent_at") and str(document.get("status") or "").upper() not in {"SENT", "ACCEPTED", "PAID"}:
            return ""
        link = next((record for record in self.store.records("call_intakes")
                     if record.get("approval_status") == "APPROVED"
                     and str(record.get("estimate_id") or "") == str(document.get("id") or "")
                     and str(record.get("customer_id") or "") == str(document.get("contact_id") or "")
                     and str(record.get("property_id") or "") == str(document.get("property_id") or "")), None)
        if not link or not self.enabled:
            return ""
        url = self.gallery_url(str(link.get("portal_source_key") or ""))
        if not url:
            return "<section class='card'><h2>Floor plan and photos</h2><p>Your project images are being synchronized. Please check back shortly.</p></section>"
        safe_url = html.escape(url, quote=True)
        return ("<section class='card'><h2>Floor plan and photos</h2>"
                f"<iframe title='Your project floor plan and photos' src='{safe_url}' referrerpolicy='no-referrer' loading='lazy' "
                "style='display:block;width:100%;height:650px;border:0;border-radius:12px'></iframe>"
                f"<a class='button secondary' href='{safe_url}' target='_blank' rel='noopener noreferrer'>Open project images</a></section>")

    async def sync_one(self, intake: dict[str, Any]) -> None:
        if intake.get("approval_status") != "APPROVED":
            return
        intake_id = str(intake["id"])
        customer = self.store.record("contacts", str(intake.get("customer_id") or ""))
        prop = self.store.record("properties", str(intake.get("property_id") or ""))
        job = self.store.record("roomflow_jobs", str(intake.get("roomflow_job_id") or ""))
        if not customer or not prop or not job:
            raise RuntimeError("Approved intake is missing a linked customer, property, or RoomFlow job")
        if any(str(row.get("workspace_id") or "") != str(intake.get("workspace_id") or "") for row in (customer, prop, job)):
            raise RuntimeError("Linked records do not belong to the approved workspace")
        if str(prop.get("contact_id") or "") != str(customer["id"]):
            raise RuntimeError("Service property does not belong to the approved customer")
        if str(job.get("contact_id") or "") != str(customer["id"]) or str(job.get("property_id") or "") != str(prop["id"]):
            raise RuntimeError("RoomFlow job does not belong to the approved customer and property")
        identity = {"organization_id": str(intake["organization_id"]), "workspace_id": str(intake["workspace_id"]), "job_id": str(intake["job_id"])}
        if not intake.get("portal_job_id"):
            address = ", ".join(str(prop.get("service_" + key) or prop.get(key) or "").strip() for key in ("street", "city", "state", "postal_code"))
            result = await self.request("upsert-job", {**identity, "customer_id": str(customer["id"]), "property_id": str(prop["id"]),
                "roomflow_job_id": str(job["id"]), "estimate_id": str(intake["estimate_id"]), "customer_name": str(customer.get("name") or ""),
                "address": address, "summary": str(intake.get("summary") or intake.get("service_reason") or "")[:5000]})
            expected_key = hashlib.sha256(json.dumps([identity[key] for key in ("organization_id", "workspace_id", "job_id")], separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
            if result.get("source_key") != expected_key or not isinstance(result.get("portal_job_id"), int) or result["portal_job_id"] <= 0:
                raise RuntimeError("Photo portal returned invalid job identifiers")
            intake = self.store.update_record("call_intakes", intake_id, {"portal_job_id": result["portal_job_id"],
                "portal_source_key": expected_key, "portal_url": self.origin + "/portal/job.php?id=" + str(result["portal_job_id"]),
                "portal_sync_status": "CONNECTED"}, actor_id="portal-sync")
            self.store.update_record("roomflow_jobs", str(job["id"]), {"portal_job_id": result["portal_job_id"], "portal_url": intake["portal_url"]}, actor_id="portal-sync")
        path = layout_path(self.store, job)
        if path:
            image = path.read_bytes()
            digest = hashlib.sha256(image).hexdigest()
            if intake.get("portal_layout_sha256") != digest:
                result = await self.request("save-layout", {**identity, "sha256": digest, "image_base64": base64.b64encode(image).decode()})
                if result.get("sha256") != digest:
                    raise RuntimeError("Photo portal floor plan verification failed")
                self.store.update_record("call_intakes", intake_id, {"portal_layout_sha256": digest}, actor_id="portal-sync")
        # Use existing ERP adapters only after staff approval. Exact-email ambiguity stops sync.
        if not intake.get("gauzy_contact_id") or not intake.get("gauzy_project_id"):
            context = await self.providers.gauzy_context()
            if not context.get("sync_enabled"):
                raise RuntimeError("ERP synchronization needs setup")
            contact_id = str(intake.get("gauzy_contact_id") or customer.get("gauzy_contact_id") or "")
            if not contact_id:
                email = str(customer.get("email") or customer.get("primaryEmail") or "").strip().lower()
                if not email:
                    raise RuntimeError("Add the customer's email to finish ERP synchronization")
                response = await self.providers._gauzy_request("GET", "/organization-contact/", params={"data": json.dumps({"relations": [], "findInput": {
                    "tenantId": context["tenant_id"], "organizationId": context["organization_id"], "primaryEmail": email}})})
                matches = [row for row in self.providers._provider_items(response) if str(row.get("primaryEmail") or "").strip().lower() == email]
                if len(matches) > 1:
                    raise RuntimeError("More than one ERP customer has this email; staff must resolve the duplicate")
                remote = matches[0] if matches else await self.providers.full_gauzy_create_contact(customer, context)
                contact_id = str(remote.get("id") or "")
                if not contact_id:
                    raise RuntimeError("ERP did not return a customer identifier")
                self.store.update_record("contacts", str(customer["id"]), {"gauzy_contact_id": contact_id}, actor_id="portal-sync")
                self.store.update_call_intake_links(intake_id, gauzy_contact_id=contact_id, actor_id="portal-sync")
            if not intake.get("gauzy_project_id"):
                remote = await self.providers.full_gauzy_create_project(prop, context, contact_id=contact_id)
                project_id = str(remote.get("id") or "")
                if not project_id:
                    raise RuntimeError("ERP did not return a project identifier")
                self.store.update_call_intake_links(intake_id, gauzy_contact_id=contact_id, gauzy_project_id=project_id, actor_id="portal-sync")
            self.store.update_record("call_intakes", intake_id, {"erp_sync_status": "CONNECTED"}, actor_id="portal-sync")
        current = self.store.record("call_intakes", intake_id) or {}
        if current.get("portal_sync_error") or current.get("portal_retry_at"):
            self.store.update_record("call_intakes", intake_id, {"portal_sync_error": "", "portal_retry_at": 0}, actor_id="portal-sync")

    async def run(self) -> None:
        from .photo_portal import PhotoPortal
        browser = PhotoPortal(self)
        while True:
            for upload in self.store.records("portal_uploads"):
                if upload.get("status") != "PENDING" or float(upload.get("retry_at") or 0) > time.time():
                    continue
                await browser.sync_upload(upload)
            for intake in self.store.records("call_intakes"):
                if intake.get("approval_status") != "APPROVED" or float(intake.get("portal_retry_at") or 0) > time.time():
                    continue
                try:
                    await self.sync_one(intake)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    # Do not persist provider payloads, authentication headers, or secret exception text.
                    detail = str(error) if isinstance(error, RuntimeError) and not str(error).startswith("Floodman ERP ") else "Connection unavailable; synchronization will retry"
                    self.store.update_record("call_intakes", str(intake["id"]), {"portal_sync_error": detail[:200], "portal_retry_at": time.time() + 60}, actor_id="portal-sync")
            await asyncio.sleep(10)

    async def start(self) -> None:
        if self.enabled and self.task is None:
            self.task = asyncio.create_task(self.run(), name="floodman-portal-sync")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
