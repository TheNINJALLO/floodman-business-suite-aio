"""Private, restart-safe Office provider setup. No customer or card data lives here."""
from __future__ import annotations

import asyncio
import copy
import json
import os
import ipaddress
import re
import socket
import smtplib
import ssl
import tempfile
import threading
import time
from dataclasses import replace
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Any

import httpx
from email_validator import validate_email, EmailNotValidError

SQUARE_HOSTS = {"sandbox": "https://connect.squareupsandbox.com", "production": "https://connect.squareup.com"}


class SetupError(ValueError):
    pass


def email_address(value: str) -> str:
    try:
        return validate_email(value, check_deliverability=False).normalized
    except EmailNotValidError:
        raise SetupError("Enter a valid email address.") from None


def field(values: dict, key: str, maximum: int = 320) -> str:
    value = str(values.get(key) or "").strip()
    if len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise SetupError("A setup field is too long or contains an invalid character.")
    return value


def smtp_connection(config: dict):
    """Certificate-verified TLS; no downgrade or credential-bearing plaintext."""
    context = ssl.create_default_context()
    client = None
    try:
        smtp_class, ssl_class = smtplib.SMTP, smtplib.SMTP_SSL
        if config.get("managed"):
            addresses = socket.getaddrinfo(config["host"], config["port"], type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
                raise SetupError("Use a public SMTP provider, not an internal server address.")
            endpoint = (addresses[0][4][0], config["port"])

            class PublicSMTP(smtplib.SMTP):
                def _get_socket(self, host, port, timeout):
                    return socket.create_connection(endpoint, timeout, self.source_address)

            class PublicSMTPSSL(smtplib.SMTP_SSL):
                def _get_socket(self, host, port, timeout):
                    raw = socket.create_connection(endpoint, timeout, self.source_address)
                    try:
                        return self.context.wrap_socket(raw, server_hostname=host)
                    except Exception:
                        raw.close()
                        raise

            # Pin the validated address, retaining the original TLS hostname;
            # DNS changes between validation and connect cannot reach local services.
            smtp_class, ssl_class = PublicSMTP, PublicSMTPSSL
        if config["security"] == "tls":
            client = ssl_class(config["host"], config["port"], timeout=15, context=context)
        else:
            client = smtp_class(config["host"], config["port"], timeout=15)
            client.ehlo()
            if config["security"] == "starttls":
                client.starttls(context=context)
                client.ehlo()
            elif config.get("username"):
                raise SetupError("SMTP sign-in requires TLS.")
        if config.get("username"):
            client.login(config["username"], config["password"])
        return client
    except Exception:
        if client is not None:
            client.close()
        raise


def smtp_check(config: dict) -> None:
    with smtp_connection(config) as client:
        code, _ = client.noop()
        if code != 250:
            raise SetupError("The mail server did not accept the connection check.")


def smtp_deliver(config: dict, message: EmailMessage) -> None:
    with smtp_connection(config) as client:
        refused = client.send_message(message)
        if refused:
            raise SetupError("The mail server refused the recipient.")


class IntegrationSetup:
    def __init__(self, settings):
        self.base = settings
        self.directory = Path(settings.data_dir).resolve() / "private-integrations"
        self.path = self.directory / "settings.json"
        self.lock = threading.RLock()

    def read(self) -> dict:
        with self.lock:
            if not self.path.exists():
                return {"schema": 1, "revision": 0}
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
                if value.get("schema") != 1 or not isinstance(value.get("revision"), int):
                    raise ValueError()
                for key in ("email", "square"):
                    if key in value and not isinstance(value[key], dict):
                        raise ValueError()
                return value
            except (OSError, ValueError, TypeError, AttributeError):
                raise SetupError("Saved provider settings could not be read. Restore the private settings backup; delivery and payments have not fallen back to test mode.") from None

    def _write(self, value: dict) -> None:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        handle, name = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=self.directory)
        try:
            os.chmod(name, 0o600)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(value, stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def mutate(self, revision: int, change) -> dict:
        with self.lock:
            state = self.read()
            if state["revision"] != revision:
                raise SetupError("Settings changed in another window. Refresh this page and try again.")
            change(state)
            state["revision"] += 1
            self._write(state)
            return state

    def save(self, kind: str, values: dict, revision: int) -> dict:
        def change(state):
            entry = state.setdefault(kind, {})
            old = entry.get("draft") or entry.get("active") or {}
            if kind == "square":
                environment = field(values, "environment")
                if environment not in SQUARE_HOSTS:
                    raise SetupError("Choose Square Sandbox or Production.")
                token = field(values, "access_token", 2048)
                if not token and old.get("environment") == environment:
                    token = old.get("access_token", "")
                app_id, location = field(values, "application_id", 128), field(values, "location_id", 128)
                if not token or not app_id:
                    raise SetupError("Add the application ID and access token for the selected Square environment.")
                if not re.fullmatch(r"[A-Za-z0-9_-]+", app_id) or (location and not re.fullmatch(r"[A-Za-z0-9_-]+", location)):
                    raise SetupError("Use the application and location IDs from Square.")
                draft = dict(environment=environment, application_id=app_id, location_id=location, access_token=token)
            elif kind == "email":
                host, username = field(values, "host", 253).lower(), field(values, "username")
                security = field(values, "security")
                # No URLs, arbitrary ports, or access to local application services.
                if not re.fullmatch(r"(?=.{1,253}$)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or "." not in host or host.endswith((".local", ".localhost")) or host == "localhost":
                    raise SetupError("Enter your mail provider's SMTP hostname, without https://.")
                try:
                    port = int(values.get("port", 587))
                except (TypeError, ValueError):
                    raise SetupError("Choose SMTP port 587 or 465.") from None
                if (security, port) not in {("starttls", 587), ("tls", 465)}:
                    raise SetupError("Use STARTTLS on port 587, or TLS on port 465.")
                password = str(values.get("password") or "")
                same_account = all(old.get(k) == v for k, v in (("host", host), ("username", username), ("port", port), ("security", security)))
                if not password and same_account:
                    password = old.get("password", "")
                if not username or not password or len(password) > 2048:
                    raise SetupError("Enter the SMTP username and password. A new server or account needs its own password.")
                draft = dict(host=host, port=port, security=security, username=username, password=password, managed=True,
                             from_email=email_address(field(values, "from_email")), from_name=field(values, "from_name", 120) or "Floodman")
            else:
                raise SetupError("Unknown setup section.")
            entry.update(draft=draft, checked_at=0, check_message="Saved. Check the connection next.", locations=[])
        return self.mutate(revision, change)

    async def check(self, kind: str, revision: int) -> dict:
        state = self.read()
        if state["revision"] != revision:
            raise SetupError("Settings changed. Refresh this page.")
        draft = copy.deepcopy(state.get(kind, {}).get("draft"))
        if not draft:
            raise SetupError("Save the settings before checking the connection.")
        locations = []
        try:
            if kind == "square":
                async with httpx.AsyncClient(timeout=15, verify=True, follow_redirects=False) as client:
                    response = await client.get(SQUARE_HOSTS[draft["environment"]] + "/v2/locations", headers={
                        "Authorization": "Bearer " + draft["access_token"], "Square-Version": self.base.square_version})
                response.raise_for_status()
                locations = [{"id": row["id"], "name": row.get("name") or row["id"]} for row in response.json().get("locations", [])
                             if row.get("status") == "ACTIVE" and "CREDIT_CARD_PROCESSING" in row.get("capabilities", []) and row.get("currency") == "USD"]
                if not draft.get("location_id") and len(locations) == 1:
                    draft["location_id"] = locations[0]["id"]
                valid = any(row["id"] == draft.get("location_id") for row in locations)
                message = "Square account and USD card-processing location checked. Application ID and checkout still need a Sandbox payment test." if valid else "Square account reached. Choose an active USD card-processing location, save, then check again."
            else:
                await asyncio.to_thread(smtp_check, draft)
                valid, message = True, "SMTP TLS connection and sign-in checked. Send yourself a test to confirm inbox delivery."
        except Exception:
            valid = False
            message = "Connection failed. Check the environment, credentials and provider access permissions." if kind == "square" else "Connection failed. Check the SMTP host, port, TLS mode and app password."
        def change(current):
            current[kind].update(draft=draft, checked_at=time.time() if valid else 0, check_message=message, locations=locations)
        return self.mutate(revision, change)

    def activate(self, kind: str, revision: int, confirmed: bool) -> dict:
        def change(state):
            entry = state.get(kind, {})
            if not confirmed:
                raise SetupError("Confirm that you want to enable this service.")
            if not entry.get("checked_at") or time.time() - entry["checked_at"] > 900:
                raise SetupError("Check the saved connection again before enabling it (checks expire after 15 minutes).")
            entry["active"] = copy.deepcopy(entry["draft"])
            entry["enabled"] = True
        return self.mutate(revision, change)

    def disable(self, kind: str, revision: int) -> dict:
        return self.mutate(revision, lambda state: state.setdefault(kind, {}).update(enabled=False))

    @property
    def call_email_path(self):
        data_root = os.getenv("DATA_DIR", "")
        return Path(data_root).resolve() / "email-settings.json" if data_root else None

    def copy_call_email(self, revision: int):
        path = self.call_email_path
        try:
            if not path:
                raise ValueError()
            values = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(values, dict):
                raise ValueError()
        except (OSError, ValueError):
            raise SetupError("Call Center email settings are unavailable. Enter your email provider settings here.") from None
        # Copy into a draft only. Never modify or enable Voice delivery here.
        return self.save("email", values, revision)

    async def test_email(self, revision: int, recipient: str) -> dict:
        recipient = email_address(recipient)
        config = {}
        def reserve(state):
            nonlocal config
            entry = state.get("email", {})
            if not entry.get("checked_at") or time.time() - entry["checked_at"] > 900:
                raise SetupError("Check the saved email connection before sending a test.")
            if time.time() - entry.get("last_test_at", 0) < 60:
                raise SetupError("Wait one minute before sending another test email.")
            config = copy.deepcopy(entry["draft"])
            entry["last_test_at"] = time.time()
        state = self.mutate(revision, reserve)  # Reserve locally before sending; repeated POSTs cannot resend.
        message = EmailMessage()
        message["From"] = formataddr((config["from_name"], config["from_email"]))
        message["To"], message["Subject"] = recipient, "Floodman email setup test"
        message.set_content("This test was requested from Floodman Payments & email setup. If you can read it, this inbox received the message. No customer document was sent.")
        try:
            await asyncio.to_thread(smtp_deliver, config, message)
        except Exception:
            raise SetupError("The test could not be confirmed. Check the recipient and provider settings before retrying; it may already have been accepted.") from None
        return state

    def effective(self):
        state, values = self.read(), {}
        square = state.get("square", {})
        if "enabled" in square:
            active = square.get("active") or {}
            environment = active.get("environment", "sandbox")
            values.update(square_environment=environment, square_base_url=SQUARE_HOSTS[environment],
                          square_access_token=active.get("access_token", ""), square_application_id=active.get("application_id", ""),
                          square_location_id=active.get("location_id", ""), square_verify_tls=True, square_web_sdk_url="",
                          payments_enabled=bool(square.get("enabled")) and self.base.payments_enabled)
        email = state.get("email", {})
        if "enabled" in email:
            active = email.get("active") or {}
            values.update(smtp_delivery_enabled=bool(email.get("enabled")), smtp_host=active.get("host", ""), smtp_port=active.get("port", 587),
                          smtp_security=active.get("security", "starttls"), smtp_username=active.get("username", ""), smtp_password=active.get("password", ""),
                          smtp_from_email=active.get("from_email", ""), smtp_from_name=active.get("from_name", "Floodman"))
            values["smtp_managed"] = True
        return replace(self.base, **values)

    @staticmethod
    def email_config(settings) -> dict:
        return dict(host=settings.smtp_host, port=settings.smtp_port, security=settings.smtp_security,
                    username=settings.smtp_username, password=settings.smtp_password,
                    from_email=settings.smtp_from_email or settings.gauzy_admin_email or "office@floodman.com", from_name=settings.smtp_from_name, managed=settings.smtp_managed)
