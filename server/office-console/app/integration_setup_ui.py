"""Owner-only, progressive disclosure setup forms; secrets are write-only."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .integration_setup import SetupError
from .ui import esc

BASE = "/office/service-setup"


def build_setup_router(service, settings, current_user, page):
    router = APIRouter()
    signing_key = secrets.token_bytes(32)

    def owner():
        user = current_user() or {}
        if user.get("role") != "OWNER" or user.get("status") != "ACTIVE":
            raise HTTPException(403, "Only the owner can change provider settings.")
        return user

    def ticket(request, revision, stamp=None):
        stamp = int(time.time()) if stamp is None else stamp
        identity = str(owner()["id"]) + ":" + request.cookies.get("floodman_session", "")
        value = f"{identity}:{revision}:{stamp}"
        return f"{stamp}." + hmac.new(signing_key, value.encode(), hashlib.sha256).hexdigest()

    def render(request, error="", notice=""):
        owner()
        try:
            state = service.read()
        except SetupError as exc:
            response = page("Payments & email", f"<div class='callout warning' role='alert'>{esc(exc)}</div>", "settings")
            response.status_code = 503
            response.headers["Cache-Control"] = "no-store"
            return response
        revision = state["revision"]
        hidden = f"<input type='hidden' name='revision' value='{revision}'><input type='hidden' name='ticket' value='{ticket(request, revision)}'>"

        def input_field(kind, key, label, value="", type="text", required=True, placeholder=""):
            return f"<div class='field'><label for='{kind}-{key}'>{esc(label)}</label><input id='{kind}-{key}' name='{key}' type='{type}' value='{esc(value)}' maxlength='2048' autocomplete='{'new-password' if type == 'password' else 'off'}' {'required' if required else ''} placeholder='{esc(placeholder)}'></div>"

        def form(kind, action, body):
            return f"<form method='post' action='{BASE}/{kind}/{action}' autocomplete='off'>{hidden}{body}</form>"

        cards = []
        for kind, title, description in (("email", "Email", "Send estimates, invoices, receipts and message notifications."), ("square", "Square payments", "Let customers pay from their secure invoice or estimate link.")):
            entry = state.get(kind, {})
            config = entry.get("draft") or entry.get("active") or {}
            active = entry.get("active") or {}
            mode = active.get("environment", "sandbox")
            status = ("Email enabled" if kind == "email" else "Production payments enabled" if mode == "production" else "Square Sandbox enabled") if entry.get("enabled") else "Disabled" if "enabled" in entry else "Server settings in use (not checked here)" if (kind == "square" and settings.square_environment != "local") or (kind == "email" and settings.smtp_host not in {"127.0.0.1", "localhost"}) else "Local test only"
            if kind == "email":
                fields = input_field(kind, "from_email", "Sender email", config.get("from_email", ""), "email")
                fields += input_field(kind, "from_name", "Sender name", config.get("from_name", "Floodman"))
                fields += input_field(kind, "host", "SMTP server", config.get("host", ""), placeholder="smtp.your-provider.com")
                fields += f"<div class='field'><label for='email-security'>Security</label><select id='email-security' name='security'><option value='starttls'>STARTTLS (port 587)</option><option value='tls' {'selected' if config.get('security') == 'tls' else ''}>TLS (port 465)</option></select></div>"
                fields += input_field(kind, "port", "Port", config.get("port", 587), "number")
                fields += input_field(kind, "username", "SMTP username", config.get("username", ""))
                fields += input_field(kind, "password", "SMTP password or app password", type="password", required=not bool(config.get("password")), placeholder="Saved — leave blank to keep" if config.get("password") else "Provided by your email host")
                help_text = "Use the outgoing-mail details from your email provider. A changed server or username needs its password entered again."
                confirm = "Enable email for ERP documents and notifications"
            else:
                fields = f"<div class='field'><label for='square-environment'>Environment</label><select id='square-environment' name='environment'><option value='sandbox'>Sandbox — no real charges</option><option value='production' {'selected' if config.get('environment') == 'production' else ''}>Production — real payments</option></select></div>"
                fields += input_field(kind, "application_id", "Application ID", config.get("application_id", ""))
                fields += input_field(kind, "access_token", "Access token", type="password", required=not bool(config.get("access_token")), placeholder="Saved — leave blank to keep" if config.get("access_token") else "Square server access token")
                if entry.get("locations"):
                    options = "<option value=''>Choose a location</option>" + "".join(f"<option value='{esc(row['id'])}' {'selected' if row['id'] == config.get('location_id') else ''}>{esc(row['name'])}</option>" for row in entry["locations"])
                    fields += f"<div class='field'><label for='square-location_id'>Business location</label><select id='square-location_id' name='location_id'>{options}</select></div>"
                else:
                    fields += input_field(kind, "location_id", "Location ID (optional until connection check)", config.get("location_id", ""), required=False)
                help_text = "Copy these from the same application and environment in Square Developer Console. The connection check can find your location; it never charges a card."
                confirm = "I have tested Sandbox checkout and approve REAL customer payments" if config.get("environment") == "production" else "Enable Square Sandbox test payments only"
            configure = form(kind, "save", f"<p class='muted'>{help_text}</p><div class='form-grid two'>{fields}</div><button>Save {kind if kind == 'email' else 'Square'} settings</button>")
            controls = ""
            if kind == "email" and service.call_email_path and service.call_email_path.is_file():
                controls += form(kind, "copy-call-email", "<button class='secondary'>Copy Call Center email settings</button><p class='muted'>Copies to a draft without showing the password. Check and enable below; Call Center settings stay unchanged.</p>")
            if entry.get("draft"):
                controls += form(kind, "check", "<button class='secondary'>Check connection</button>")
            if entry.get("checked_at"):
                controls += form(kind, "activate", f"<label class='setup-confirm'><input type='checkbox' name='confirmed' value='yes' required> <span>{esc(confirm)}</span></label><button>Enable {'email' if kind == 'email' else 'payments'}</button>")
                if kind == "email":
                    controls += form(kind, "test", input_field(kind, "recipient", "Send a test to your email", type="email") + "<button class='secondary'>Send test email</button><p class='muted'>Sends one test, not a customer document. Check your inbox and spam folder.</p>")
            if entry.get("enabled"):
                controls += form(kind, "disable", f"<button class='secondary'>Disable {'email delivery' if kind == 'email' else 'payments'}</button>")
            boundary = "Applies to ERP emails. Call Center alerts keep their existing email settings." if kind == "email" else "Applies to Office and mobile checkout. Automated RoomFlow billing and reconciliation of changes made directly in Square still require server/webhook setup."
            cards.append(f"<section class='card setup-card' id='{kind}'><h2>{title}</h2><p>{description}</p><p class='setup-status'>{esc(status)}</p><details {'open' if not config else ''}><summary>Connection settings</summary>{configure}</details><p class='muted' role='status'>{esc(entry.get('check_message') or 'Save → check → enable. Saving does not replace an active connection.')}</p><div class='setup-controls'>{controls}</div><p class='muted'>{boundary}</p></section>")
        notices = f"<div class='callout warning' role='alert'>{esc(error)}</div>" if error else f"<div class='callout success' role='status'>{esc(notice)}</div>" if notice else ""
        body = """<style>.setup-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px;align-items:start}.setup-card,.setup-controls form,.setup-card .field{min-width:0}.setup-card p{overflow-wrap:anywhere}.setup-card input,.setup-card select{max-width:100%;min-width:0}.setup-card summary{cursor:pointer;font-weight:650;padding:12px 0}.setup-card .form-grid{margin-bottom:16px}.setup-controls{display:grid;gap:20px}.setup-confirm{display:flex;gap:10px;align-items:flex-start;margin-bottom:12px}.setup-confirm input{width:auto;flex:0 0 auto;margin-top:4px}.setup-status{font-weight:650}.setup-card button{white-space:normal}.setup-card .field input{width:100%}@media(max-width:1100px){.setup-cards{grid-template-columns:minmax(0,1fr)}}@media(max-width:540px){.setup-card .form-grid{grid-template-columns:minmax(0,1fr)}}</style>
<div class='actions'><a class='button secondary' href='/office/settings'>Back to settings</a></div>
<p>Connect payments and email here. Passwords and tokens are saved privately on the server and never displayed after saving.</p>""" + notices + "<div class='setup-cards'>" + "".join(cards) + "</div>"
        response = page("Payments & email", body, "settings")
        response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "same-origin", "X-Frame-Options": "SAMEORIGIN"})
        return response

    @router.get(BASE)
    async def setup_page(request: Request):
        notices = {"saved": "Settings saved. Your active connection has not changed.", "checked": "Connection check finished; see the result below.", "enabled": "Service enabled with the checked settings.", "disabled": "Service disabled. Saved credentials are retained privately.", "sent": "The mail server accepted the test. Confirm it arrived in your inbox; acceptance alone does not prove delivery."}
        return render(request, notice=notices.get(request.query_params.get("notice"), ""))

    @router.post(BASE + "/{kind}/{action}")
    async def setup_action(request: Request, kind: str, action: str):
        owner()
        if kind not in {"email", "square"} or action not in {"save", "check", "activate", "disable", "test", "copy-call-email"} or (action in {"test", "copy-call-email"} and kind != "email"):
            raise HTTPException(404)
        expected = urlsplit(settings.public_url)
        origin = request.headers.get("origin", "")
        if origin != f"{expected.scheme}://{expected.netloc}" or request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "Open setup from your ERP to continue.")
        if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
            raise HTTPException(415)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 16384:
                raise HTTPException(413)
        try:
            data = parse_qs(body.decode("utf-8"), max_num_fields=24, keep_blank_values=True)
            if any(len(v) != 1 for v in data.values()):
                raise ValueError()
            values = {k: v[0] for k, v in data.items()}
            revision = int(values.get("revision", ""))
            stamp = int(values.get("ticket", "").split(".")[0])
            if not 0 <= time.time() - stamp <= 1800 or not hmac.compare_digest(values["ticket"], ticket(request, revision, stamp)):
                raise ValueError()
        except (ValueError, KeyError, UnicodeError):
            raise HTTPException(403, "This setup form expired. Refresh the page.") from None
        try:
            if action == "save": service.save(kind, values, revision)
            elif action == "copy-call-email": service.copy_call_email(revision)
            elif action == "check": await service.check(kind, revision)
            elif action == "activate": service.activate(kind, revision, values.get("confirmed") == "yes")
            elif action == "disable": service.disable(kind, revision)
            else: await service.test_email(revision, values.get("recipient", ""))
        except SetupError as exc:
            response = render(request, error=str(exc))
            response.status_code = 400
            return response
        except OSError:
            response = render(request, error="Could not save private settings. Check server disk space and permissions.")
            response.status_code = 503
            return response
        notice = {"save": "saved", "copy-call-email": "saved", "check": "checked", "activate": "enabled", "disable": "disabled", "test": "sent"}[action]
        return RedirectResponse(BASE + f"?notice={notice}#{kind}", status_code=303, headers={"Cache-Control": "no-store"})

    return router
