"""Fictional credentials only; no real mail or payment calls."""
import asyncio
import json
import os
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import httpx

from app.config import Settings
from app.integration_setup import IntegrationSetup, SetupError, smtp_connection
from app.providers import ProviderClient

EMAIL = dict(host="smtp.example.com", port="587", security="starttls", username="fictional@example.com",
             password="fictional-secret-email", from_email="office@example.com", from_name="Floodman Test")
SQUARE = dict(environment="sandbox", application_id="sandbox-fictional-app", access_token="fictional-secret-square", location_id="")


def rejects(function):
    try:
        function()
    except (SetupError, OSError):
        return
    raise AssertionError("Unsafe operation accepted")


async def run():
    with tempfile.TemporaryDirectory(prefix="floodman-setup-test-") as root:
        settings = replace(Settings.from_env(), data_dir=root, internal_hmac_keys="v1:MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=",
                           ai_hmac_keys="ai:MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjI=")
        service = IntegrationSetup(settings)
        client = ProviderClient(settings)
        assert not service.path.exists()
        for change in ({"host":"https://smtp.example.com"}, {"port":"22"}, {"security":"none"}, {"password":""}, {"from_name":"Injection\r\nBcc: secret@example.com"}, {"from_email":"bad"}):
            rejects(lambda:service.save("email", {**EMAIL, **change}, 0))
        state = service.save("email", EMAIL, 0)
        assert service.effective().smtp_host == settings.smtp_host, "Saving changed delivery"
        rejects(lambda:service.activate("email", state["revision"], True))
        rejects(lambda:service.save("email", EMAIL, 0))
        with patch("app.integration_setup.smtp_check") as check:
            state = await service.check("email", state["revision"])
            check.assert_called_once()
        rejects(lambda:service.activate("email", state["revision"], False))
        state = service.activate("email", state["revision"], True)
        assert service.effective().smtp_username == EMAIL["username"]
        with patch("app.providers.smtp_deliver") as deliver:
            result = await client.send_email(to="recipient@example.com", subject="Test", text="Test", html="<p>Test</p>", attachments=[("test.pdf", b"%PDF-FICTIONAL", "application/pdf")])
            assert result["status"] == "SENT"
            config, message = deliver.call_args.args
            assert config["password"] == EMAIL["password"] and config["managed"]
            assert message["From"] == "Floodman Test <office@example.com>"
            assert len(list(message.iter_attachments())) == 1
        state = service.save("email", {**EMAIL, "password":""}, state["revision"])
        assert state["email"]["draft"]["password"] == EMAIL["password"]
        assert state["email"]["active"]["password"] == EMAIL["password"]
        rejects(lambda:service.save("email", {**EMAIL, "host":"another.example.com", "password":""}, state["revision"]))
        rejects(lambda:service.activate("email", state["revision"], True))
        with patch("app.integration_setup.smtp_check", side_effect=RuntimeError(EMAIL["password"])):
            state = await service.check("email", state["revision"])
        assert EMAIL["password"] not in state["email"]["check_message"] and not state["email"]["checked_at"]
        assert service.effective().smtp_host == EMAIL["host"], "Failed draft check changed active delivery"
        with patch("app.integration_setup.smtp_check"):
            state = await service.check("email", state["revision"])
        with patch("app.integration_setup.smtp_deliver") as deliver:
            revision = state["revision"]
            state = await service.test_email(revision, "recipient@example.com")
            assert deliver.call_count == 1
            for stale in (revision, state["revision"]):
                try: await service.test_email(stale, "recipient@example.com")
                except SetupError: pass
                else: raise AssertionError("Duplicate test email sent")
            assert deliver.call_count == 1
        state = service.disable("email", state["revision"])
        with patch("app.providers.smtp_deliver") as deliver:
            try: await client.send_email(to="recipient@example.com", subject="Test", text="Test")
            except SetupError: pass
            else: raise AssertionError("Disabled email sent")
            deliver.assert_not_called()
        state = service.save("square", SQUARE, state["revision"])
        calls = []
        def square_response(request):
            calls.append(request)
            assert request.url.host == "connect.squareupsandbox.com"
            assert request.method == "GET" and request.url.path == "/v2/locations"
            return httpx.Response(200, json={"locations":[{"id":"LOCATION-ONE", "name":"Fictional office", "status":"ACTIVE", "capabilities":["CREDIT_CARD_PROCESSING"], "currency":"USD"}, {"id":"INACTIVE", "status":"INACTIVE"}]})
        real_client = httpx.AsyncClient
        with patch("app.integration_setup.httpx.AsyncClient", side_effect=lambda **kw:real_client(transport=httpx.MockTransport(square_response), **kw)):
            state = await service.check("square", state["revision"])
        assert state["square"]["draft"]["location_id"] == "LOCATION-ONE"
        state = service.activate("square", state["revision"], True)
        assert client.square_payment_configuration()["environment"] == "sandbox"
        assert client.square_payment_configuration()["live"] and not client.square_payment_configuration()["local_mock"]
        rejects(lambda:service.save("square", {**SQUARE, "environment":"production", "access_token":""}, state["revision"]))
        with client.configuration_scope():
            before = client.settings
            state = service.disable("square", state["revision"])
            assert client.settings is before and client.settings.payments_enabled
        assert not client.settings.payments_enabled
        with patch("app.providers.httpx.AsyncClient") as remote:
            for path in ("/v2/payments", "/v2/invoices", "/v2/cards", "/v2/customers"):
                try: await client.square_request("POST", path, {"verified":True})
                except SetupError: pass
                else: raise AssertionError("Disabled Square mutation allowed")
            try: await client.create_square_payment(source_id="test", amount_cents=100, currency="USD", reference_id="test", note="test")
            except SetupError: pass
            else: raise AssertionError("Disabled payment allowed")
            remote.assert_not_called()
        assert not IntegrationSetup(settings).effective().payments_enabled, "Restart lost disable"
        state = service.save("square", {**SQUARE, "environment":"production", "access_token":"fictional-prod-secret"}, state["revision"])
        assert not service.effective().payments_enabled, "Production draft enabled payments"
        rejects(lambda:service.activate("square", state["revision"], True))
        # Disk failure must not claim success or replace an active configuration.
        snapshot = service.path.read_bytes()
        with patch("app.integration_setup.os.replace", side_effect=OSError("Fictional disk full")):
            rejects(lambda:service.disable("square", state["revision"]))
        assert service.path.read_bytes() == snapshot
        # Reject local IP resolution before any SMTP connection.
        with patch("app.integration_setup.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 587))]), patch("app.integration_setup.smtplib.SMTP") as smtp:
            rejects(lambda:smtp_connection({**EMAIL,"managed":True}))
            smtp.assert_not_called()
        # Corrupt private configuration fails closed, never silently uses mocks.
        with patch.object(Path, "read_text", return_value="corrupt"):
            rejects(lambda:IntegrationSetup(settings).effective())
        assert len(calls) == 1
        print("Provider setup: save/check/enable, secrets, TLS, disabled billing, stale forms, restart and failure checks PASS")


if __name__ == "__main__": asyncio.run(run())
