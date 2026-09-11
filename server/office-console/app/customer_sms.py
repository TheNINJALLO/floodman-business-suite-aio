"""Explicit customer consent, committed to the ERP before any synchronization."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import secrets
import time
import uuid
from datetime import UTC, datetime
from html import escape
from urllib.parse import urlsplit

from fastapi import HTTPException

from .sms_policy import CUSTOMER_DISCLOSURE, CUSTOMER_VERSION, links


def phone_number(value: str) -> str:
    raw = str(value or "").strip()
    if not re.fullmatch(r"[+0-9() .-]{10,30}", raw):
        raise ValueError("Enter a valid US mobile number without an extension.")
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        digits = "1" + digits
    if not re.fullmatch(r"1[2-9][0-9]{2}[2-9][0-9]{6}", digits):
        raise ValueError("Enter a valid 10-digit US mobile number.")
    return "+" + digits


class CustomerSms:
    def __init__(self, store, providers, settings):
        self.store, self.providers, self.settings = store, providers, settings
        self.task = None

    @property
    def organization(self):
        return self.settings.external_portal_organization_id

    def current(self, contact_id):
        return self.store.record("customer_sms_preferences", str(contact_id)) or {}

    def ticket(self, token, contact_id, *, now=None):
        issued = int(time.time() if now is None else now)
        payload = f"{issued}.{secrets.token_urlsafe(18)}"
        signature = hmac.new(self.settings.internal_hmac_keys.encode(),
                             f"customer-sms:{token}:{contact_id}:{CUSTOMER_VERSION}:{payload}".encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    def validate_ticket(self, value, token, contact_id, *, now=None):
        parts = str(value).split(".")
        if len(parts) != 3 or not re.fullmatch(r"[A-Za-z0-9_-]{24}", parts[1]) or not re.fullmatch(r"[0-9a-f]{64}", parts[2]):
            raise ValueError("Refresh the portal before saving your text preference.")
        try:
            age = int(time.time() if now is None else now) - int(parts[0])
        except ValueError as exc:
            raise ValueError("Refresh the portal before saving your text preference.") from exc
        expected = hmac.new(self.settings.internal_hmac_keys.encode(),
                            f"customer-sms:{token}:{contact_id}:{CUSTOMER_VERSION}:{'.'.join(parts[:2])}".encode(), hashlib.sha256).hexdigest()
        if not -30 <= age <= 1800 or not hmac.compare_digest(parts[2], expected):
            raise ValueError("This form expired. Refresh the portal before saving your text preference.")

    def form(self, kind, document, *, error="", notice=""):
        contact_id = str(document.get("contact_id") or "")
        if not contact_id or not self.store.record("contacts", contact_id):
            return ""
        current = self.current(contact_id)
        status = "Text updates are not enabled."
        if current.get("status") == "OPTED_IN":
            status = f"Portal preference: enabled for a number ending in {str(current.get('phone_e164', ''))[-4:]}. Replying STOP also blocks delivery."
        elif current.get("status") == "OPTED_OUT":
            status = "Text updates are turned off."
        token = str(document["public_token"])
        action = f"/customer/{escape(kind)}/{escape(token)}/sms-consent"
        ticket = self.ticket(token, contact_id)
        disable = ""
        if current.get("status") == "OPTED_IN":
            disable = f'<button type="submit" name="choice" value="disable" formnovalidate>Turn off text updates</button>'
        return f'''<section class="card" id="sms-preferences"><h2>Optional text updates</h2>
<p>{escape(status)}</p><p>Texts are optional. You can view documents, request service, and pay without enrolling.</p>
{f'<p class="notice error" role="alert">{escape(error)}</p>' if error else ''}
{f'<p class="notice good" role="status">{escape(notice)}</p>' if notice else ''}
<form method="post" action="{action}"><input type="hidden" name="ticket" value="{ticket}">
<div class="portal-honeypot" aria-hidden="true"><label>Website<input name="website" tabindex="-1" autocomplete="off"></label></div>
<div class="field"><label for="sms-mobile">Your US mobile number</label><input id="sms-mobile" type="tel" inputmode="tel" autocomplete="tel" name="phone" maxlength="30" placeholder="(231) 555-0100"></div>
<label style="display:flex;align-items:flex-start;gap:12px;line-height:1.6"><input id="sms-consent" name="consent" type="checkbox" value="yes" style="width:22px;height:22px;flex:0 0 22px;margin-top:4px"><span>{escape(CUSTOMER_DISCLOSURE)} {links()}</span></label>
<div class="actions" style="margin-top:18px"><button type="submit" name="choice" value="enable">Enable text updates</button>{disable}</div>
<p><small>Carrier approval is required before messaging starts. If you previously replied STOP, you must also reply START to remove that carrier block. This form does not override it.</small></p>
</form></section>'''

    def save(self, kind, document, *, ticket, phone, choice, consent, origin="", website=""):
        if origin and origin.rstrip("/") not in {
            f"{urlsplit(self.settings.public_url).scheme}://{urlsplit(self.settings.public_url).netloc}",
            f"{urlsplit(self.settings.customer_public_url).scheme}://{urlsplit(self.settings.customer_public_url).netloc}",
        }:
            raise HTTPException(403, "Cross-site consent submission is not allowed.")
        if website:
            raise ValueError("The preference was not saved. Please refresh and try again.")
        contact_id = str(document.get("contact_id") or "")
        if not contact_id or not self.store.record("contacts", contact_id):
            raise HTTPException(404, "Customer file not found")
        self.validate_ticket(ticket, str(document["public_token"]), contact_id)
        if choice not in {"enable", "disable"}:
            raise ValueError("Choose whether to enable or turn off texts.")
        if choice == "enable" and consent != "yes":
            raise ValueError("Check the optional SMS consent box to enable texts, or leave it unchecked to continue without texts.")
        recipient = phone_number(phone) if choice == "enable" else ""
        event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "floodman-sms-consent:" + ticket))
        fingerprint = hashlib.sha256(f"{contact_id}:{choice}:{recipient}:{consent}".encode()).hexdigest()
        now = datetime.now(UTC).isoformat()
        with self.store.lock:
            existing = self.store.record("customer_sms_events", event_id)
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise ValueError("This form was already used. Refresh before changing your preference.")
                return {**existing, "status":self.current(contact_id).get("status", existing["status"])}
            recent = [r for r in self.store.records("customer_sms_events") if r.get("contact_id") == contact_id
                      and (datetime.now(UTC) - datetime.fromisoformat(r["captured_at"])).total_seconds() < 60]
            if choice == "enable" and len(recent) >= 5:
                raise HTTPException(429, "Please wait a minute before changing your text preference again.")
            current = self.current(contact_id)
            if choice == "disable":
                recipient = current.get("phone_e164", "")
                if not recipient:
                    raise ValueError("No text enrollment exists for this customer.")
                if current.get("status") == "OPTED_OUT":
                    return current
            status = "OPTED_IN" if choice == "enable" else "OPTED_OUT"
            events = []
            if choice == "enable" and current.get("phone_e164") and current["phone_e164"] != recipient:
                events.append({"id":str(uuid.uuid5(uuid.NAMESPACE_URL, event_id + ":old-number")),
                               "phone_e164":current["phone_e164"], "status":"OPTED_OUT", "fingerprint":fingerprint})
            events.append({"id":event_id, "phone_e164":recipient, "status":status, "fingerprint":fingerprint})
            for event in events:
                event.update({"schema_version":1, "organization_id":self.organization, "contact_id":contact_id,
                              "document_kind":kind, "document_id":str(document["id"]), "captured_at":now,
                              "source":"FLOODMAN_CUSTOMER_PORTAL", "disclosure_version":CUSTOMER_VERSION,
                              "disclosure_text":CUSTOMER_DISCLOSURE, "sync_status":"PENDING", "attempts":0})
            before = self.store.snapshot()
            try:
                self.store.bulk_upsert_records({"customer_sms_events":events,
                    "customer_sms_preferences":[{"id":contact_id, "organization_id":self.organization,
                        "phone_e164":recipient,"status":status,"captured_at":now,"event_id":event_id,
                        "schema_version":1,"disclosure_version":CUSTOMER_VERSION}]}, actor_id="customer-portal")
            except Exception:
                # No worker may see a consent event whose durable write failed.
                self.store._state = before
                raise
        return events[-1]

    async def sync_once(self):
        pending = sorted((r for r in self.store.records("customer_sms_events") if r.get("sync_status") == "PENDING"),
                         key=lambda r: (r["captured_at"], r["id"]))[:20]
        for event in pending:
            payload = {key:event[key] for key in ("organization_id","contact_id","phone_e164","status","captured_at","disclosure_version","disclosure_text")}
            payload["idempotency_key"] = event["id"]
            try:
                result = await self.providers.orchestrator.request("POST", "/internal/v1/customer-sms/consent", payload, timeout=5)
                if result.get("recorded") is not True:
                    raise RuntimeError("Consent sync was not acknowledged")
            except Exception:
                self.store.update_record("customer_sms_events", event["id"], {"attempts":int(event.get("attempts",0))+1}, actor_id="consent-sync")
                break
            self.store.update_record("customer_sms_events", event["id"], {"sync_status":"SYNCED"}, actor_id="consent-sync")

    async def start(self):
        async def run():
            while True:
                try:
                    await self.sync_once()
                except Exception:
                    pass  # Durable pending records remain available for retry.
                await asyncio.sleep(15)
        self.task = asyncio.create_task(run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
