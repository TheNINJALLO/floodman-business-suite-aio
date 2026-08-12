from __future__ import annotations

import base64
import hashlib
import hmac
import re
from pathlib import Path

import pytest

from email_validator import validate_email

from app.util import classify_start_state, make_pdf, twilio_signature


def test_make_pdf_has_valid_header_and_eof() -> None:
    value = make_pdf("Local Test", "Floodman")
    assert value.startswith(b"%PDF-1.4")
    assert value.rstrip().endswith(b"%%EOF")


def test_twilio_signature_matches_exact_url_and_sorted_parameters() -> None:
    url = "https://example.ngrok.app/webhooks/twilio/inbound"
    params = {"From": "+13135550199", "Body": "Balance?", "MessageSid": "SM1"}
    canonical = url + "BodyBalance?From+13135550199MessageSidSM1"
    expected = base64.b64encode(hmac.new(b"test-token", canonical.encode(), hashlib.sha1).digest()).decode()
    assert twilio_signature("test-token", url, params) == expected


def test_sandbox_customer_email_is_accepted_by_orchestrator_validator() -> None:
    main_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    source = main_path.read_text(encoding="utf-8")
    match = re.search(r'"email"\s*:\s*"([^"]+)"', source)
    assert match, "The demo payload email could not be found."
    email = match.group(1)
    validated = validate_email(email, check_deliverability=False)
    assert validated.normalized == "jane.local@example.com"


def test_windows_local_email_defaults_are_accepted() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env.windows.example"
    if not env_path.is_file():
        pytest.skip("Windows environment test is not applicable to the Pterodactyl AIO package")
    values: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value

    for key in ("GAUZY_EMAIL", "SMTP_FROM_EMAIL", "SMTP_REPLY_TO"):
        validate_email(values[key], check_deliverability=False)

    staff_emails = [item.strip() for item in values["AR_STAFF_EMAILS"].split(",") if item.strip()]
    assert staff_emails
    for email in staff_emails:
        validate_email(email, check_deliverability=False)


def test_start_button_waits_for_async_deposit_reconciliation() -> None:
    assert classify_start_state("AUTHORIZATION_SIGNED") == "WAIT"
    assert classify_start_state("DEPOSIT_PUBLISHED") == "WAIT"
    assert classify_start_state("DEPOSIT_PAID") == "READY"
    assert classify_start_state("IN_PROGRESS") == "ALREADY_STARTED"
    assert classify_start_state("AUTHORIZATION_SENT") == "BLOCKED"
