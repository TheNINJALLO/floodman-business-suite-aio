from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

PASSWORD_ITERATIONS = 310_000

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "OWNER": {"*"},
    "ADMIN": {
        "dashboard.view", "contacts.manage", "properties.manage", "estimates.manage", "invoices.manage",
        "payments.manage", "documents.manage", "notes.manage", "messages.manage", "receivables.manage",
        "time.manage", "tasks.manage", "intelligence.manage", "alerts.manage", "members.manage",
        "connections.manage", "imports.manage", "apps.view",
    },
    "OFFICE_MANAGER": {
        "dashboard.view", "contacts.manage", "properties.manage", "estimates.manage", "invoices.manage",
        "payments.manage", "documents.manage", "notes.manage", "messages.manage", "receivables.manage",
        "time.view", "tasks.manage", "intelligence.view", "alerts.manage", "apps.view",
    },
    "BILLING": {
        "dashboard.view", "contacts.view", "properties.view", "estimates.view", "invoices.manage",
        "payments.manage", "documents.view", "notes.manage", "messages.manage", "receivables.manage",
        "alerts.view", "apps.view",
    },
    "ESTIMATOR": {
        "dashboard.view", "contacts.manage", "properties.manage", "estimates.manage", "invoices.view",
        "payments.view", "documents.manage", "notes.manage", "messages.view", "time.self", "tasks.manage",
        "apps.view",
    },
    "TECHNICIAN": {
        "dashboard.view", "contacts.view", "properties.view", "estimates.view", "invoices.view",
        "documents.view", "notes.manage", "messages.view", "time.self", "tasks.manage", "apps.view",
    },
    "VIEWER": {
        "dashboard.view", "contacts.view", "properties.view", "estimates.view", "invoices.view",
        "payments.view", "documents.view", "notes.view", "messages.view", "receivables.view",
        "time.view", "tasks.view", "intelligence.view", "alerts.view", "apps.view",
    },
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def hash_password(password: str, *, iterations: int = PASSWORD_ITERATIONS) -> str:
    if len(password) < 10:
        raise ValueError("Password must contain at least 10 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
    )


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        expected = _decode(digest_text)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _decode(salt_text), iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def new_token(prefix: str = "") -> str:
    value = secrets.token_urlsafe(32)
    return f"{prefix}{value}" if prefix else value


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiry(days: int = 14) -> str:
    return (utcnow() + timedelta(days=days)).isoformat()


def invite_expiry(days: int = 7) -> str:
    return (utcnow() + timedelta(days=days)).isoformat()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def permissions_for(user: dict[str, Any] | None) -> set[str]:
    if not user:
        return set()
    role = str(user.get("role") or "VIEWER").upper()
    values = set(ROLE_PERMISSIONS.get(role, set()))
    values.update(str(item) for item in (user.get("permissions") or []))
    values.difference_update(str(item) for item in (user.get("denied_permissions") or []))
    return values


def has_permission(user: dict[str, Any] | None, permission: str) -> bool:
    values = permissions_for(user)
    if "*" in values or permission in values:
        return True
    family = permission.split(".", 1)[0]
    return f"{family}.manage" in values or (permission.endswith(".view") and f"{family}.manage" in values)
