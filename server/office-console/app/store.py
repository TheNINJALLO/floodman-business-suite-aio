from __future__ import annotations

import json
import os
import threading
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .auth import (
    ROLE_PERMISSIONS,
    has_permission,
    hash_password,
    invite_expiry,
    new_token,
    parse_time,
    session_expiry,
    token_hash,
    utcnow,
    verify_password,
)


ARCHIVE_ID_FIELDS = {
    "contacts": "legacy_contact_id",
    "properties": "legacy_property_id",
    "estimates": "legacy_estimate_id",
    "estimate_lines": "legacy_line_id",
    "invoices": "legacy_invoice_id",
    "payments": "legacy_payment_id",
    "documents": "legacy_document_id",
    "notes": "legacy_note_id",
}

OPERATION_KINDS = {
    "contacts", "properties", "estimates", "invoices", "payments", "documents", "notes", "time_entries", "tasks",
    "roomflow_jobs", "catalog_items", "public_links", "payment_attempts", "mobile_devices", "mobile_refresh_tokens",
    "mobile_audit", "appointments", "announcements", "notifications", "push_tokens", "calendar_subscriptions",
    "customer_threads", "customer_messages",
    "estimate_revisions", "invoice_revisions", "roomflow_imports", "roomflow_workspaces", "roomflow_workspace_selections",
    "roomflow_capture_rooms", "roomflow_capture_operations", "roomflow_capture_audit",
    "call_intakes", "call_intake_audit"
}

DEFAULT_STATE: dict[str, Any] = {
    "profile": {
        "company_name": "Floodman",
        "legal_name": "",
        "office_email": "",
        "billing_email": "",
        "office_phone": "",
        "timezone": "America/Detroit",
        "street": "",
        "city": "",
        "state": "MI",
        "postal_code": "",
    },
    "checklist": {
        "owner_created": False,
        "profile_saved": False,
        "connections_tested": False,
        "import_reviewed": False,
        "legal_reviewed": False,
        "messaging_reviewed": False,
        "setup_complete": False,
    },
    "connections": {},
    "link_config": {
        "roomflow_url": "/roomflow/",
        "gauzy_mode": "FULL_LOCAL",
        "gauzy_base_url": "http://host.docker.internal:3000/api",
        "gauzy_web_url": "http://localhost:9000",
        "square_mode": "LOCAL_MOCK",
        "square_base_url": "http://127.0.0.1:9003/square",
        "square_location_id": "local-square-location",
        "documenso_mode": "FULL_LOCAL",
        "documenso_base_url": "http://127.0.0.1:9001/api/v2",
        "documenso_web_url": "http://localhost:9001",
        "twilio_mode": "LOCAL_MOCK",
        "twilio_base_url": "http://127.0.0.1:9003/twilio/2010-04-01",
        "twilio_account_sid": "ACLOCALFLOODMAN",
        "twilio_messaging_service_sid": "MGLOCALFLOODMAN",
        "smtp_mode": "LOCAL_CAPTURE",
        "smtp_host": "local-lab",
        "smtp_port": 1025,
        "messaging_ai_provider": "deterministic",
    },
    "users": {},
    "invites": {},
    "sessions": {},
    "external_mappings": {"gauzy": {}},
    "operations": {kind: {} for kind in OPERATION_KINDS},
    "archive": {kind: {} for kind in ARCHIVE_ID_FIELDS},
    "imports": [],
    "last_notice": "",
}


def _safe_relative(name: str) -> Path:
    normalized = str(name or "").replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ValueError("unsafe import file path")
    return Path(*path.parts)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class CaptureOperationConflict(ValueError):
    pass


class CaptureOperationNotFound(KeyError):
    pass


class OfficeStore:
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.import_root = self.root / "imports"
        self.import_root.mkdir(parents=True, exist_ok=True)
        self.upload_root = self.root / "uploads"
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "office-state.json"
        self.lock = threading.RLock()
        self._state = self._load()
        self._apply_runtime_defaults()
        self._prune_security_records()

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return deepcopy(DEFAULT_STATE)
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            corrupt = self.state_path.with_suffix(f".corrupt-{int(datetime.now(UTC).timestamp())}.json")
            os.replace(self.state_path, corrupt)
            return deepcopy(DEFAULT_STATE)
        state = deepcopy(DEFAULT_STATE)
        for key, value in loaded.items():
            if key in {"profile", "checklist", "link_config"} and isinstance(value, dict):
                state[key].update(value)
            elif key == "archive" and isinstance(value, dict):
                for kind in ARCHIVE_ID_FIELDS:
                    if isinstance(value.get(kind), dict):
                        state["archive"][kind].update(value[kind])
            elif key == "operations" and isinstance(value, dict):
                for kind in OPERATION_KINDS:
                    if isinstance(value.get(kind), dict):
                        state["operations"][kind].update(value[kind])
            elif key in {"users", "invites", "sessions"} and isinstance(value, dict):
                state[key].update(value)
            elif key == "external_mappings" and isinstance(value, dict):
                for provider, mappings in value.items():
                    if isinstance(mappings, dict):
                        state["external_mappings"].setdefault(provider, {}).update(mappings)
            else:
                state[key] = value
        if state.get("users"):
            state["checklist"]["owner_created"] = True
        return state

    def _save(self) -> None:
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(self._state, indent=2, sort_keys=True, default=str), encoding="utf-8")
        os.replace(temp, self.state_path)

    def _apply_runtime_defaults(self) -> None:
        """Synchronize the AIO runtime's real company identity into Office.

        Pterodactyl already asks for the company, owner, and time zone before
        the suite starts. Those values are configuration, not unfinished setup.
        Review-only checklist items remain manual and are never falsely marked.
        """

        changed = False
        company = os.getenv("FLOODMAN_COMPANY_NAME", "").strip()
        owner_email = os.getenv("FLOODMAN_OWNER_EMAIL", "").strip().lower()
        timezone = os.getenv("TZ", "America/Detroit").strip() or "America/Detroit"
        with self.lock:
            profile = self._state["profile"]
            if company and profile.get("company_name") != company:
                profile["company_name"] = company
                changed = True
            if owner_email and not str(profile.get("office_email") or "").strip():
                profile["office_email"] = owner_email
                changed = True
            if profile.get("timezone") != timezone:
                profile["timezone"] = timezone
                changed = True
            if company or owner_email:
                if not self._state["checklist"].get("profile_saved"):
                    self._state["checklist"]["profile_saved"] = True
                    changed = True
            if self._state.get("users") and not self._state["checklist"].get("owner_created"):
                self._state["checklist"]["owner_created"] = True
                changed = True
            if changed:
                self._save()

    def _prune_security_records(self) -> None:
        now = utcnow()
        changed = False
        with self.lock:
            for name in ("sessions", "invites"):
                for key, value in list(self._state.get(name, {}).items()):
                    expires = parse_time(value.get("expires_at"))
                    if expires and expires <= now:
                        self._state[name].pop(key, None)
                        changed = True
            if changed:
                self._save()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return deepcopy(self._state)

    def profile(self) -> dict[str, Any]:
        return self.snapshot()["profile"]

    def checklist(self) -> dict[str, bool]:
        return self.snapshot()["checklist"]

    def link_config(self) -> dict[str, Any]:
        return self.snapshot()["link_config"]

    def update_profile(self, values: dict[str, Any]) -> None:
        with self.lock:
            self._state["profile"].update(values)
            self._state["checklist"]["profile_saved"] = True
            self._state["last_notice"] = "Company profile saved."
            self._save()

    def update_checklist(self, values: dict[str, bool]) -> None:
        with self.lock:
            for key, value in values.items():
                if key in self._state["checklist"]:
                    self._state["checklist"][key] = bool(value)
            self._save()

    def update_link_config(self, values: dict[str, Any]) -> None:
        allowed = set(DEFAULT_STATE["link_config"])
        with self.lock:
            for key, value in values.items():
                if key in allowed:
                    self._state["link_config"][key] = value
            self._state["last_notice"] = "Connection plan saved. Apply provider secrets through .env.windows."
            self._save()

    def save_connections(self, values: dict[str, Any]) -> None:
        with self.lock:
            self._state["connections"] = values
            self._state["checklist"]["connections_tested"] = True
            self._state["last_notice"] = "Connection tests completed."
            self._save()

    def set_notice(self, value: str) -> None:
        with self.lock:
            self._state["last_notice"] = value
            self._save()

    # ------------------------------------------------------------------
    # Local staff identity and permissions
    # ------------------------------------------------------------------
    def has_users(self) -> bool:
        return bool(self.snapshot().get("users"))

    def create_owner(self, name: str, email: str, password: str) -> dict[str, Any]:
        email_key = email.strip().lower()
        with self.lock:
            if self._state["users"]:
                raise ValueError("The owner account already exists.")
            user_id = str(uuid.uuid4())
            user = {
                "id": user_id,
                "name": name.strip(),
                "email": email_key,
                "role": "OWNER",
                "password_hash": hash_password(password),
                "permissions": [],
                "denied_permissions": [],
                "status": "ACTIVE",
                "created_at": _now(),
                "updated_at": _now(),
            }
            self._state["users"][user_id] = user
            self._state["checklist"]["owner_created"] = True
            if not self._state["profile"].get("office_email"):
                self._state["profile"]["office_email"] = email_key
            self._state["last_notice"] = "Primary owner account created."
            self._save()
            return deepcopy(user)

    def list_users(self) -> list[dict[str, Any]]:
        users = list(self.snapshot().get("users", {}).values())
        return sorted(users, key=lambda item: (item.get("role") != "OWNER", str(item.get("name") or "").lower()))

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        value = self.snapshot().get("users", {}).get(user_id)
        return dict(value) if value else None

    def user_by_email(self, email: str) -> dict[str, Any] | None:
        key = email.strip().lower()
        for user in self.list_users():
            if str(user.get("email") or "").lower() == key:
                return user
        return None

    def authenticate(self, email: str, password: str) -> dict[str, Any] | None:
        user = self.user_by_email(email)
        if not user or user.get("status") != "ACTIVE":
            return None
        return user if verify_password(password, str(user.get("password_hash") or "")) else None

    def upsert_gauzy_user(self, identity: dict[str, Any]) -> dict[str, Any]:
        """Create or refresh a Floodman-module identity from a verified Floodman ERP account."""
        email_key = str(identity.get("email") or "").strip().lower()
        if not email_key:
            raise ValueError("Floodman ERP did not return an email address.")
        with self.lock:
            existing = next(
                (item for item in self._state.get("users", {}).values() if str(item.get("email") or "").lower() == email_key),
                None,
            )
            if existing:
                existing["gauzy_user_id"] = str(identity.get("gauzy_user_id") or existing.get("gauzy_user_id") or "")
                existing["gauzy_employee_id"] = str(identity.get("gauzy_employee_id") or existing.get("gauzy_employee_id") or "")
                existing["gauzy_role"] = str(identity.get("gauzy_role") or existing.get("gauzy_role") or "USER")
                existing["auth_source"] = "GAUZY" if not existing.get("password_hash") else "LOCAL_AND_GAUZY"
                existing["status"] = "ACTIVE"
                existing["updated_at"] = _now()
                self._save()
                return deepcopy(existing)

            if not self._state.get("users") and not bool(identity.get("is_gauzy_admin")):
                raise ValueError("A Floodman ERP administrator must create the first Floodman owner account.")
            user_id = str(uuid.uuid4())
            role = "OWNER" if not self._state.get("users") else str(identity.get("suggested_office_role") or "VIEWER").upper()
            if role not in {"OWNER", "ADMIN", "OFFICE_MANAGER", "BILLING", "ESTIMATOR", "TECHNICIAN", "VIEWER"}:
                role = "VIEWER"
            user = {
                "id": user_id,
                "name": str(identity.get("name") or email_key),
                "email": email_key,
                "role": role,
                "password_hash": "",
                "permissions": [],
                "denied_permissions": [],
                "status": "ACTIVE",
                "auth_source": "GAUZY",
                "gauzy_user_id": str(identity.get("gauzy_user_id") or ""),
                "gauzy_employee_id": str(identity.get("gauzy_employee_id") or ""),
                "gauzy_role": str(identity.get("gauzy_role") or "USER"),
                "created_at": _now(),
                "updated_at": _now(),
            }
            self._state["users"][user_id] = user
            if role == "OWNER":
                self._state["checklist"]["owner_created"] = True
                if not self._state["profile"].get("office_email"):
                    self._state["profile"]["office_email"] = email_key
            self._state["last_notice"] = f"Floodman ERP member {email_key} connected to Floodman modules."
            self._save()
            return deepcopy(user)

    def create_session(self, user_id: str) -> str:
        token = new_token("fos_")
        with self.lock:
            self._state["sessions"][token_hash(token)] = {
                "user_id": user_id,
                "created_at": _now(),
                "expires_at": session_expiry(),
            }
            self._save()
        return token

    def user_for_session(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        key = token_hash(token)
        with self.lock:
            session = self._state.get("sessions", {}).get(key)
            if not session:
                return None
            expires = parse_time(session.get("expires_at"))
            if expires and expires <= utcnow():
                self._state["sessions"].pop(key, None)
                self._save()
                return None
            user = self._state.get("users", {}).get(str(session.get("user_id") or ""))
            if not user or user.get("status") != "ACTIVE":
                return None
            return deepcopy(user)

    def delete_session(self, token: str | None) -> None:
        if not token:
            return
        with self.lock:
            self._state.get("sessions", {}).pop(token_hash(token), None)
            self._save()

    def create_invite(
        self,
        name: str,
        email: str,
        role: str,
        created_by: str,
        phone: str = "",
    ) -> tuple[dict[str, Any], str]:
        email_key = email.strip().lower()
        name_value = name.strip()
        role_value = role.strip().upper()
        if len(name_value) < 2:
            raise ValueError("Enter the staff member's full name.")
        if not email_key or "@" not in email_key:
            raise ValueError("Enter a valid staff email address.")
        if role_value not in ROLE_PERMISSIONS or role_value == "OWNER":
            raise ValueError("Choose one of the listed staff access levels.")
        if self.user_by_email(email_key):
            raise ValueError("A member with that email already exists.")
        phone_value = self._staff_phone(phone)
        token = new_token("invite_")
        invite_id = str(uuid.uuid4())
        invite = {
            "id": invite_id,
            "name": name_value,
            "email": email_key,
            "phone": phone_value,
            "role": role_value,
            "token_hash": token_hash(token),
            "created_by": created_by,
            "created_at": _now(),
            "expires_at": invite_expiry(),
            "status": "PENDING",
        }
        with self.lock:
            self._state["invites"][invite_id] = invite
            self._state["last_notice"] = f"Invitation created for {email_key}."
            self._save()
        return deepcopy(invite), token

    def list_invites(self) -> list[dict[str, Any]]:
        return sorted(self.snapshot().get("invites", {}).values(), key=lambda item: item.get("created_at", ""), reverse=True)

    def invite_for_token(self, token: str) -> dict[str, Any] | None:
        digest = token_hash(token)
        for invite in self.list_invites():
            if invite.get("token_hash") == digest and invite.get("status") == "PENDING":
                expires = parse_time(invite.get("expires_at"))
                if not expires or expires > utcnow():
                    return invite
        return None

    def accept_invite(self, token: str, password: str) -> dict[str, Any]:
        invite = self.invite_for_token(token)
        if not invite:
            raise ValueError("Invitation is invalid or expired.")
        user_id = str(uuid.uuid4())
        user = {
            "id": user_id,
            "name": invite.get("name") or invite.get("email"),
            "email": invite.get("email"),
            "phone": invite.get("phone") or "",
            "role": invite.get("role") or "VIEWER",
            "password_hash": hash_password(password),
            "permissions": [],
            "denied_permissions": [],
            "status": "ACTIVE",
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self.lock:
            self._state["users"][user_id] = user
            self._state["invites"][invite["id"]]["status"] = "ACCEPTED"
            self._state["invites"][invite["id"]]["accepted_at"] = _now()
            self._save()
        return deepcopy(user)

    def update_user(
        self,
        user_id: str,
        *,
        role: str | None = None,
        status: str | None = None,
        password: str | None = None,
        phone: str | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            user = self._state["users"].get(user_id)
            if not user:
                raise KeyError(user_id)
            if user.get("role") == "OWNER" and status and status != "ACTIVE":
                raise ValueError("The primary owner cannot be disabled.")
            if role and user.get("role") != "OWNER":
                role_value = role.upper()
                if role_value not in ROLE_PERMISSIONS or role_value == "OWNER":
                    raise ValueError("Choose one of the listed staff access levels.")
                user["role"] = role_value
            if status:
                status_value = status.upper()
                if status_value not in {"ACTIVE", "DISABLED"}:
                    raise ValueError("Choose Active or Disabled for the account status.")
                user["status"] = status_value
            if password:
                user["password_hash"] = hash_password(password)
            if phone is not None:
                user["phone"] = self._staff_phone(phone)
            user["updated_at"] = _now()
            self._save()
            return deepcopy(user)

    # ------------------------------------------------------------------
    # Cross-system external ID mappings
    # ------------------------------------------------------------------
    def external_mapping(self, provider: str, key: str) -> str | None:
        value = self.snapshot().get("external_mappings", {}).get(provider, {}).get(key)
        return str(value) if value else None

    def set_external_mapping(self, provider: str, key: str, external_id: str) -> None:
        with self.lock:
            self._state.setdefault("external_mappings", {}).setdefault(provider, {})[key] = external_id
            self._save()

    def external_mappings(self, provider: str) -> dict[str, str]:
        return dict(self.snapshot().get("external_mappings", {}).get(provider, {}))

    # ------------------------------------------------------------------
    # Operational records created through Floodman Office
    # ------------------------------------------------------------------
    def create_record(self, kind: str, values: dict[str, Any], *, actor_id: str | None = None) -> dict[str, Any]:
        if kind not in OPERATION_KINDS:
            raise KeyError(kind)
        record_id = str(values.get("id") or uuid.uuid4())
        now = _now()
        record = {
            **values,
            "id": record_id,
            "source": values.get("source") or "FLOODMAN_OFFICE",
            "created_at": values.get("created_at") or now,
            "updated_at": now,
            "created_by": values.get("created_by") or actor_id,
            "updated_by": actor_id,
        }
        with self.lock:
            self._state["operations"][kind][record_id] = record
            self._save()
        return deepcopy(record)

    def create_record_if_absent(
        self,
        kind: str,
        record_id: str,
        values: dict[str, Any],
        *,
        actor_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Create one operational record once and return whether it was new.

        Payment callbacks, mobile retries, and customer form resubmissions can
        legitimately repeat.  Keeping the existence check and write under the
        store lock prevents those retries from producing duplicate alerts or
        conversation messages.
        """
        if kind not in OPERATION_KINDS:
            raise KeyError(kind)
        stable_id = str(record_id or "").strip()
        if not stable_id:
            raise ValueError("A stable record ID is required.")
        with self.lock:
            existing = self._state["operations"][kind].get(stable_id)
            if existing is not None:
                return deepcopy(existing), False
            now = _now()
            record = {
                **values,
                "id": stable_id,
                "source": values.get("source") or "FLOODMAN_OFFICE",
                "created_at": values.get("created_at") or now,
                "updated_at": now,
                "created_by": values.get("created_by") or actor_id,
                "updated_by": actor_id,
            }
            self._state["operations"][kind][stable_id] = record
            self._save()
            return deepcopy(record), True

    def bulk_upsert_records(
        self,
        records_by_kind: dict[str, list[dict[str, Any]]],
        *,
        actor_id: str | None = None,
    ) -> dict[str, dict[str, int]]:
        """Create or update many operational records with one durable write.

        Large customer exports can contain thousands of contacts and properties.
        Saving the entire JSON state after every individual row makes imports
        unnecessarily slow on mobile-hosted Pterodactyl storage. This method
        applies the already validated records under one lock and writes once.
        """
        now = _now()
        result: dict[str, dict[str, int]] = {}
        with self.lock:
            for kind, values_list in records_by_kind.items():
                if kind not in OPERATION_KINDS:
                    raise KeyError(kind)
                target = self._state["operations"][kind]
                created = 0
                updated = 0
                for values in values_list:
                    record_id = str(values.get("id") or uuid.uuid4())
                    existing = target.get(record_id)
                    if existing is None:
                        record = {
                            **values,
                            "id": record_id,
                            "source": values.get("source") or "FLOODMAN_OFFICE",
                            "created_at": values.get("created_at") or now,
                            "updated_at": now,
                            "created_by": values.get("created_by") or actor_id,
                            "updated_by": actor_id,
                        }
                        target[record_id] = record
                        created += 1
                    else:
                        for key, value in values.items():
                            if key not in {"id", "created_at", "created_by"}:
                                existing[key] = value
                        existing["updated_at"] = now
                        existing["updated_by"] = actor_id
                        updated += 1
                result[kind] = {"created": created, "updated": updated}
            self._save()
        return result

    def update_record(self, kind: str, record_id: str, values: dict[str, Any], *, actor_id: str | None = None) -> dict[str, Any]:
        if kind not in OPERATION_KINDS:
            raise KeyError(kind)
        with self.lock:
            record = self._state["operations"][kind].get(record_id)
            if not record:
                raise KeyError(record_id)
            for key, value in values.items():
                if key not in {"id", "created_at", "created_by"}:
                    record[key] = value
            record["updated_at"] = _now()
            record["updated_by"] = actor_id
            self._save()
            return deepcopy(record)

    def delete_record(self, kind: str, record_id: str) -> None:
        if kind not in OPERATION_KINDS:
            raise KeyError(kind)
        with self.lock:
            self._state["operations"][kind].pop(record_id, None)
            self._save()

    def record(self, kind: str, record_id: str) -> dict[str, Any] | None:
        if kind not in OPERATION_KINDS:
            raise KeyError(kind)
        value = self.snapshot()["operations"].get(kind, {}).get(record_id)
        return dict(value) if value else None

    def records(self, kind: str) -> list[dict[str, Any]]:
        if kind not in OPERATION_KINDS:
            raise KeyError(kind)
        values = list(self.snapshot()["operations"].get(kind, {}).values())
        return sorted(values, key=lambda item: item.get("updated_at", ""), reverse=True)

    def _call_intake_notifications(self, operations, payload, intake_id, workspace_id, caller_name, actor_id, now):
        notification_ids: list[str] = []
        recipient_ids: list[str] = []
        for user in self._state.get("users", {}).values():
            if str(user.get("status") or "ACTIVE").upper() != "ACTIVE" or not has_permission(user, "call_intakes.view"):
                continue
            user_id = str(user.get("id") or "")
            selection_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"floodman:roomflow-supabase:workspace-selection:{user_id}",
            ))
            selection = operations["roomflow_workspace_selections"].get(selection_id)
            selected_workspace_id = str((selection or {}).get("workspace_id") or "")
            if not selected_workspace_id:
                workspaces = list(operations["roomflow_workspaces"].values())
                if workspaces:
                    selected_workspace_id = str(min(
                        workspaces,
                        key=lambda value: (
                            0 if value.get("roomflow_organization_id") or value.get("source_organization_id")
                            else (1 if value.get("imported") else 2),
                            str(value.get("name") or "").casefold(),
                            str(value.get("id") or ""),
                        ),
                    ).get("id") or "")
            if selected_workspace_id != workspace_id:
                continue
            notification_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"floodman-call-notification:{intake_id}:{user_id}"))
            notification = operations["notifications"].get(notification_id) or {
                "id": notification_id,
                "user_id": user_id,
                "workspace_id": workspace_id,
                "kind": "AI_CALL_INTAKE",
                "reference_id": intake_id,
                "status": "UNREAD",
                "email_status": "PENDING" if user.get("email") else "NO_EMAIL",
                "sms_status": "PENDING" if user.get("phone") else "NO_PHONE",
                "push_status": "READY" if any(
                    str(token.get("user_id") or "") == user_id and str(token.get("status") or "ACTIVE") == "ACTIVE"
                    for token in operations["push_tokens"].values()
                ) else "MOBILE_FEED",
                "source": "AI_CALLING",
                "created_at": now,
                "created_by": actor_id,
            }
            notification.update({
                "title": f"Incoming call: {caller_name}",
                "body": str(payload.get("summary") or payload.get("service_reason") or "Open the call intake for live details.")[:500],
                "action_url": f"/office/calls/{intake_id}",
                "updated_at": now,
                "updated_by": actor_id,
            })
            operations["notifications"][notification_id] = notification
            notification_ids.append(notification_id)
            recipient_ids.append(user_id)

        return notification_ids, recipient_ids

    def project_call_intake(
        self, payload: dict[str, Any], *, actor_id: str = "floodman-orchestrator",
        require_approval: bool = False, approved_by: str = "",
        selected_customer_id: str = "", selected_property_id: str = "",
    ) -> dict[str, Any]:
        """Atomically project one AI call into the local operational record graph.

        Exact workspace-scoped phone/email matches are the only automatic identity
        links. Conflicting matches are retained as a review item and never guessed.
        RoomFlow and estimate drafts contain no measurements, quantities, or prices;
        those facts must be added by staff after field capture.
        """

        intake_id = str(payload.get("intake_id") or "").strip()
        workspace_id = str(payload.get("workspace_id") or "").strip()
        sequence = int(payload.get("event_sequence") or 0)
        if not intake_id or not workspace_id:
            raise ValueError("Call intake ID and workspace ID are required.")
        now = _now()
        caller = dict(payload.get("caller") or {})
        property_input = dict(payload.get("property") or {})
        proposed = dict(payload.get("proposed_ids") or {})
        required_ids = {
            "customer_id",
            "property_id",
            "job_id",
            "roomflow_job_id",
            "estimate_id",
            "note_id",
            "task_id",
            "appointment_id",
        }
        missing_ids = sorted(key for key in required_ids if not str(proposed.get(key) or "").strip())
        if missing_ids:
            raise ValueError(f"Stable proposed IDs are required: {', '.join(missing_ids)}.")

        with self.lock:
            previous_operations = self._state["operations"]
            operations = deepcopy(previous_operations)
            if workspace_id not in operations["roomflow_workspaces"]:
                raise ValueError("Call intake workspace does not exist.")
            existing_intake = operations["call_intakes"].get(intake_id)
            if existing_intake and approved_by and existing_intake.get("approval_status") == "APPROVED":
                return {**deepcopy(existing_intake), "replayed": True}
            if existing_intake and not approved_by and int(existing_intake.get("event_sequence", -1)) >= sequence:
                return {**deepcopy(existing_intake), "replayed": True}

            if require_approval and not approved_by and (existing_intake or {}).get("approval_status") != "APPROVED":
                record = {
                    **deepcopy(existing_intake or {}), **deepcopy(payload), "id": intake_id,
                    "approval_status": "PENDING", "review_status": "PENDING_APPROVAL",
                    "projection_status": "PENDING", "source": "AI_CALLING",
                    "created_at": (existing_intake or {}).get("created_at") or now,
                    "updated_at": now, "updated_by": actor_id,
                }
                operations["call_intakes"][intake_id] = record
                notification_ids, recipient_ids = self._call_intake_notifications(
                    operations, payload, intake_id, workspace_id,
                    str(caller.get("name") or "Incoming caller"), actor_id, now,
                )
                self._state["operations"] = operations
                try:
                    self._save()
                except Exception:
                    self._state["operations"] = previous_operations
                    raise
                return {**deepcopy(record), "notification_ids": notification_ids, "recipient_user_ids": recipient_ids, "replayed": False}

            if (existing_intake or {}).get("approval_status") == "APPROVED":
                caller = deepcopy(existing_intake.get("approved_caller") or caller)
                property_input = deepcopy(existing_intake.get("approved_property") or property_input)
                selected_customer_id = str(existing_intake.get("customer_id") or "")
                selected_property_id = str(existing_intake.get("property_id") or "")

            phone_key = self._normalized_phone(caller.get("phone_e164") or caller.get("phone"))
            phone_verified = bool(caller.get("phone_verified"))
            email_key = self._normalized_email(caller.get("email"))
            contact_matches: dict[str, dict[str, Any]] = {}
            for contact in operations["contacts"].values():
                if str(contact.get("workspace_id") or "") != workspace_id:
                    continue
                same_phone = phone_verified and bool(phone_key) and self._normalized_phone(
                    contact.get("phone") or contact.get("primaryPhone")
                ) == phone_key
                if same_phone:
                    contact_matches[str(contact["id"])] = contact

            review_reasons = [str(value)[:200] for value in (payload.get("review_reasons") or []) if str(value).strip()]
            if selected_customer_id:
                contact = operations["contacts"].get(selected_customer_id)
                if not contact or str(contact.get("workspace_id") or "") != workspace_id:
                    raise ValueError("Selected customer does not belong to this workspace.")
            elif len(contact_matches) > 1:
                review_reasons.append("AMBIGUOUS_CUSTOMER_MATCH")
                contact: dict[str, Any] | None = None
            elif contact_matches:
                contact = next(iter(contact_matches.values()))
            else:
                contact_id = str(proposed.get("customer_id") or "").strip()
                if not contact_id:
                    raise ValueError("A stable proposed customer ID is required.")
                first_name = str(caller.get("first_name") or "").strip()
                last_name = str(caller.get("last_name") or "").strip()
                display_name = str(caller.get("name") or "").strip() or " ".join(
                    value for value in (first_name, last_name) if value
                ).strip()
                if not display_name:
                    display_name = f"Caller ending {phone_key[-4:]}" if len(phone_key) >= 4 else "Unidentified caller"
                    review_reasons.append("CALLER_NAME_REQUIRED")
                contact = {
                    "id": contact_id,
                    "workspace_id": workspace_id,
                    "name": display_name,
                    "first_name": first_name,
                    "last_name": last_name,
                    "company": str(caller.get("company") or "").strip(),
                    "email": email_key,
                    "phone": str(caller.get("phone_e164") or caller.get("phone") or "").strip(),
                    "status": "LEAD",
                    "lead_source": "AI_CALLING",
                    "notes": "Created from a verified AI calling webhook; review incomplete identity fields.",
                    "source": "AI_CALLING",
                    "created_at": now,
                    "updated_at": now,
                    "created_by": actor_id,
                    "updated_by": actor_id,
                }
                operations["contacts"][contact_id] = contact

            if contact is not None and str(contact.get("source") or "") == "AI_CALLING":
                for key, value in {
                    "first_name": caller.get("first_name"),
                    "last_name": caller.get("last_name"),
                    "company": caller.get("company"),
                    "email": email_key,
                    "phone": caller.get("phone_e164") or caller.get("phone"),
                }.items():
                    if value:
                        contact[key] = str(value).strip()
                supplied_name = str(caller.get("name") or "").strip() or " ".join(
                    str(caller.get(key) or "").strip() for key in ("first_name", "last_name")
                ).strip()
                if supplied_name:
                    contact["name"] = supplied_name
                contact["updated_at"] = now
                contact["updated_by"] = actor_id

            property_record: dict[str, Any] | None = None
            roomflow_job: dict[str, Any] | None = None
            estimate: dict[str, Any] | None = None
            contact_id = str((contact or {}).get("id") or "")
            address = {
                "street": str(property_input.get("street") or "").strip(),
                "city": str(property_input.get("city") or "").strip(),
                "state": str(property_input.get("state") or "").strip(),
                "postal_code": str(property_input.get("postal_code") or "").strip(),
            }
            address_complete = all(address.values())
            if selected_property_id:
                selected_property = operations["properties"].get(selected_property_id)
                if (
                    not selected_property or str(selected_property.get("workspace_id") or "") != workspace_id
                    or str(selected_property.get("contact_id") or "") != contact_id
                ):
                    raise ValueError("Selected property does not belong to the selected customer.")
                address = {key: str(selected_property.get("service_" + key) or selected_property.get(key) or "").strip() for key in address}
                address_complete = all(address.values())
            if contact and address_complete:
                address_key = "|".join(address.values()).casefold()
                property_record = next(
                    (
                        value for value in operations["properties"].values()
                        if str(value.get("workspace_id") or "") == workspace_id
                        and str(value.get("contact_id") or "") == contact_id
                        and "|".join(
                            str(value.get(field) or "").strip()
                            for field in ("service_street", "service_city", "service_state", "service_postal_code")
                        ).casefold() == address_key
                    ),
                    None,
                )
                if selected_property_id:
                    property_record = operations["properties"][selected_property_id]
                if property_record is None:
                    property_id = str(proposed.get("property_id") or "").strip()
                    if not property_id:
                        raise ValueError("A stable proposed property ID is required.")
                    property_record = {
                        "id": property_id,
                        "workspace_id": workspace_id,
                        "contact_id": contact_id,
                        "name": str(property_input.get("name") or "Service property").strip(),
                        "property_name": str(property_input.get("name") or "Service property").strip(),
                        "property_type": str(property_input.get("property_type") or "").strip(),
                        "service_street": address["street"],
                        "service_city": address["city"],
                        "service_state": address["state"],
                        "service_postal_code": address["postal_code"],
                        "insurance_company": str(property_input.get("insurer") or "").strip(),
                        "claim_number": str(property_input.get("claim_number") or "").strip(),
                        "status": "INTAKE_DRAFT",
                        "source": "AI_CALLING",
                        "created_at": now,
                        "updated_at": now,
                        "created_by": actor_id,
                        "updated_by": actor_id,
                    }
                    operations["properties"][property_id] = property_record
            elif contact:
                review_reasons.append("SERVICE_PROPERTY_REQUIRED")

            if contact and property_record:
                job_id = str(proposed.get("job_id") or "").strip()
                roomflow_job_id = str(proposed.get("roomflow_job_id") or "").strip()
                estimate_id = str(proposed.get("estimate_id") or "").strip()
                if not all((job_id, roomflow_job_id, estimate_id)):
                    raise ValueError("Stable job, RoomFlow job, and estimate IDs are required.")
                roomflow_job = operations["roomflow_jobs"].get(roomflow_job_id) or {
                    "id": roomflow_job_id,
                    "roomflow_job_id": job_id,
                    "roomflow_source_id": job_id,
                    "workspace_id": workspace_id,
                    "contact_id": contact_id,
                    "property_id": property_record["id"],
                    "estimate_id": estimate_id,
                    "job_name": str(payload.get("service_reason") or "Incoming call intake").strip(),
                    "name": str(payload.get("service_reason") or "Incoming call intake").strip(),
                    "status": "INTAKE_DRAFT",
                    "measurement_status": "NOT_CAPTURED",
                    "snapshot": {"rooms": [], "levels": [], "capturedMeasurements": [], "costing": {"customItems": []}},
                    "source": "AI_CALLING",
                    "created_at": now,
                    "created_by": actor_id,
                }
                roomflow_job.update({"updated_at": now, "updated_by": actor_id})
                operations["roomflow_jobs"][roomflow_job_id] = roomflow_job
                estimate = operations["estimates"].get(estimate_id) or {
                    "id": estimate_id,
                    "estimate_number": f"CALL-{intake_id[:8].upper()}",
                    "workspace_id": workspace_id,
                    "contact_id": contact_id,
                    "property_id": property_record["id"],
                    "roomflow_job_id": roomflow_job_id,
                    "title": str(payload.get("service_reason") or "Incoming call estimate draft").strip(),
                    "project_summary": str(payload.get("summary") or "").strip(),
                    "status": "DRAFT",
                    "publication_status": "UNPUBLISHED",
                    "pricing_status": "NOT_PRICED",
                    "review_required": True,
                    "currency": "USD",
                    "sections": [],
                    "line_items": [],
                    "subtotal_cents": 0,
                    "tax_total_cents": 0,
                    "total_cents": 0,
                    "deposit_type": "NONE",
                    "deposit_cents": 0,
                    "deposit_balance_cents": 0,
                    "deposit_paid_cents": 0,
                    "deposit_due_stage": "AFTER_AUTHORIZATION",
                    "source": "AI_CALLING",
                    "created_at": now,
                    "created_by": actor_id,
                }
                estimate.update({"updated_at": now, "updated_by": actor_id})
                operations["estimates"][estimate_id] = estimate

            review_reasons = list(dict.fromkeys(review_reasons))
            task_id = str(proposed.get("task_id") or "").strip()
            if not task_id:
                raise ValueError("A stable follow-up task ID is required.")
            task = operations["tasks"].get(task_id) or {
                "id": task_id,
                "workspace_id": workspace_id,
                "title": "Review incoming AI call",
                "description": str(payload.get("summary") or payload.get("service_reason") or "Review the call intake and complete missing details.")[:1000],
                "priority": "URGENT" if str(payload.get("urgency") or "").upper() in {"EMERGENCY", "URGENT"} else "HIGH",
                "status": "OPEN",
                "reference_type": "CALL_INTAKE",
                "reference_id": intake_id,
                "assigned_user_id": None,
                "assigned_to_name": "Unassigned",
                "source": "AI_CALLING",
                "created_at": now,
                "created_by": actor_id,
            }
            task.update({"updated_at": now, "updated_by": actor_id})
            operations["tasks"][task_id] = task

            appointment_id: str | None = None
            appointment_input = dict(payload.get("appointment") or {})
            if bool(appointment_input.get("requested")):
                appointment_id = str(proposed.get("appointment_id") or "").strip()
                if not appointment_id:
                    raise ValueError("A stable appointment request ID is required.")
                appointment = operations["appointments"].get(appointment_id) or {
                    "id": appointment_id,
                    "workspace_id": workspace_id,
                    "contact_id": contact_id or None,
                    "property_id": (property_record or {}).get("id"),
                    "call_intake_id": intake_id,
                    "title": "Call intake appointment request",
                    "appointment_type": "FOLLOW_UP",
                    "requested_window": str(appointment_input.get("requested_window") or "").strip(),
                    "status": "REQUESTED_UNCONFIRMED",
                    "assigned_user_ids": [],
                    "source": "AI_CALLING",
                    "created_at": now,
                    "created_by": actor_id,
                }
                appointment.update({"updated_at": now, "updated_by": actor_id})
                operations["appointments"][appointment_id] = appointment

            note_id = str(proposed.get("note_id") or "").strip()
            note_text = str(
                payload.get("summary")
                or payload.get("service_reason")
                or "Incoming AI call; staff review is required to complete the intake."
            )[:5000]
            note = operations["notes"].get(note_id) or {
                "id": note_id,
                "workspace_id": workspace_id,
                "intake_id": intake_id,
                "pinned": False,
                "source": "AI_CALLING",
                "created_at": now,
                "created_by": actor_id,
            }
            note.update({
                "entity_type": "CONTACT" if contact_id else "CALL_INTAKE",
                "entity_id": contact_id or intake_id,
                "contact_id": contact_id or None,
                "property_id": (property_record or {}).get("id"),
                "note_type": "CALL",
                "body": note_text,
                "note": note_text,
                "transcript_available": bool(payload.get("transcript_available")),
                "updated_at": now,
                "updated_by": actor_id,
            })
            operations["notes"][note_id] = note

            projection_status = "REVIEW_REQUIRED" if review_reasons else "PROJECTED"
            record = {
                **(deepcopy(existing_intake) if existing_intake else {}),
                **deepcopy(payload),
                "id": intake_id,
                "intake_id": intake_id,
                "workspace_id": workspace_id,
                "event_sequence": sequence,
                "customer_id": contact_id or None,
                "property_id": (property_record or {}).get("id"),
                "job_id": str(proposed.get("job_id") or "") if roomflow_job else None,
                "roomflow_job_id": (roomflow_job or {}).get("id"),
                "estimate_id": (estimate or {}).get("id"),
                "note_id": note_id,
                "task_id": task_id,
                "appointment_id": appointment_id,
                "review_reasons": review_reasons,
                "review_status": projection_status,
                "projection_status": projection_status,
                "created_at": (existing_intake or {}).get("created_at") or now,
                "updated_at": now,
                "created_by": (existing_intake or {}).get("created_by") or actor_id,
                "updated_by": actor_id,
                "source": "AI_CALLING",
            }
            if (existing_intake or {}).get("approval_status") == "APPROVED":
                record.update({"caller": deepcopy(caller), "property": deepcopy(property_input), "review_status": "APPROVED"})
            if approved_by:
                if not contact_id or not property_record or not roomflow_job:
                    raise ValueError("Confirm a customer and complete service address before approving this call.")
                record.update({
                    "approval_status": "APPROVED", "approved_by": approved_by, "approved_at": now,
                    "approved_caller": deepcopy(caller), "approved_property": deepcopy(property_input),
                    "review_status": "APPROVED", "portal_sync_status": "PENDING", "erp_sync_status": "PENDING",
                })
            operations["call_intakes"][intake_id] = record

            notification_ids, recipient_ids = self._call_intake_notifications(
                operations, payload, intake_id, workspace_id,
                str((contact or {}).get("name") or "Incoming caller"), actor_id, now,
            )

            audit_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"floodman-call-audit:{intake_id}:{sequence}"))
            operations["call_intake_audit"].setdefault(audit_id, {
                "id": audit_id,
                "intake_id": intake_id,
                "workspace_id": workspace_id,
                "event_type": str(payload.get("event_type") or ""),
                "event_sequence": sequence,
                "projection_status": projection_status,
                "linked_record_ids": {
                    "customer_id": contact_id or None,
                    "property_id": (property_record or {}).get("id"),
                    "roomflow_job_id": (roomflow_job or {}).get("id"),
                    "estimate_id": (estimate or {}).get("id"),
                    "note_id": note_id,
                    "task_id": task_id,
                    "appointment_id": appointment_id,
                },
                "created_at": now,
                "source": "AI_CALLING",
            })
            self._state["operations"] = operations
            try:
                self._save()
            except Exception:
                self._state["operations"] = previous_operations
                raise
            return {
                **deepcopy(record),
                "notification_ids": notification_ids,
                "recipient_user_ids": recipient_ids,
                "replayed": False,
            }

    def update_call_intake_links(
        self,
        intake_id: str,
        *,
        gauzy_contact_id: str = "",
        gauzy_project_id: str = "",
        actor_id: str = "floodman-orchestrator",
    ) -> dict[str, Any]:
        """Idempotently attach ERP IDs after the local projection already exists."""

        with self.lock:
            record = self._state["operations"]["call_intakes"].get(intake_id)
            if not record:
                raise KeyError(intake_id)
            if gauzy_contact_id:
                record["gauzy_contact_id"] = gauzy_contact_id
                if record.get("customer_id"):
                    key = f"contact:{record['customer_id']}"
                    self._state.setdefault("external_mappings", {}).setdefault("gauzy", {})[key] = gauzy_contact_id
            if gauzy_project_id:
                record["gauzy_project_id"] = gauzy_project_id
                if record.get("property_id"):
                    key = f"property:{record['property_id']}"
                    self._state.setdefault("external_mappings", {}).setdefault("gauzy", {})[key] = gauzy_project_id
            record["gauzy_sync_status"] = "SYNCED" if gauzy_contact_id else "REVIEW_REQUIRED"
            record["updated_at"] = _now()
            record["updated_by"] = actor_id
            self._save()
            return deepcopy(record)

    def commit_roomflow_capture_operation(
        self,
        *,
        operation_id: str,
        request_hash: str,
        action: str,
        workspace_id: str,
        job_id: str,
        room_id: str,
        room: dict[str, Any] | None,
        expected_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        """Atomically apply or replay one RoomFlow Capture operation.

        The operation receipt, room revision, parent job snapshot, and redacted
        audit entry share one durable Office-state write. This keeps mobile
        retries from creating duplicate rooms or partially updating a job.
        """

        normalized_action = str(action or "").upper()
        if normalized_action not in {"CREATE", "UPDATE", "DELETE"}:
            raise ValueError("unsupported capture operation")
        now = _now()
        with self.lock:
            operations = self._state["operations"]
            receipts = operations["roomflow_capture_operations"]
            existing_receipt = receipts.get(operation_id)
            if existing_receipt:
                if str(existing_receipt.get("request_hash") or "") != request_hash:
                    raise CaptureOperationConflict("operation ID was already used for different capture data")
                return {"replayed": True, **deepcopy(existing_receipt.get("result") or {})}

            jobs = operations["roomflow_jobs"]
            job = jobs.get(job_id)
            if not job or str(job.get("workspace_id") or "") != workspace_id:
                raise CaptureOperationNotFound("RoomFlow job not found")

            rooms = operations["roomflow_capture_rooms"]
            existing = rooms.get(room_id)
            if existing and (str(existing.get("workspace_id") or "") != workspace_id or str(existing.get("job_id") or "") != job_id):
                raise CaptureOperationNotFound("Captured room not found")

            if normalized_action == "CREATE":
                if existing and not existing.get("deleted_at"):
                    raise CaptureOperationConflict("captured room already exists")
                if expected_revision not in {0, -1}:
                    raise CaptureOperationConflict("new captured rooms must start at revision 0")
                revision = 1
                created_at = now
                created_by = actor_id
            else:
                if not existing or existing.get("deleted_at"):
                    raise CaptureOperationNotFound("Captured room not found")
                current_revision = int(existing.get("revision") or 0)
                if expected_revision != current_revision:
                    raise CaptureOperationConflict(f"captured room changed on another device; current revision is {current_revision}")
                revision = current_revision + 1
                created_at = str(existing.get("created_at") or now)
                created_by = str(existing.get("created_by") or actor_id)

            if normalized_action == "DELETE":
                record = {
                    **deepcopy(existing or {}),
                    "revision": revision,
                    "deleted_at": now,
                    "updated_at": now,
                    "updated_by": actor_id,
                }
                result_room: dict[str, Any] | None = None
            else:
                if not room:
                    raise ValueError("capture room is required")
                record = {
                    "id": room_id,
                    "workspace_id": workspace_id,
                    "job_id": job_id,
                    "schema_version": int(room.get("schemaVersion") or 0),
                    "revision": revision,
                    "room": deepcopy(room),
                    "deleted_at": None,
                    "source": "ROOMFLOW_CAPTURE",
                    "created_at": created_at,
                    "updated_at": now,
                    "created_by": created_by,
                    "updated_by": actor_id,
                }
                result_room = deepcopy(room)
            rooms[room_id] = record

            snapshot = deepcopy(job.get("snapshot") if isinstance(job.get("snapshot"), dict) else {})
            snapshot_rooms = [
                deepcopy(value)
                for value in snapshot.get("rooms", [])
                if isinstance(value, dict) and str(value.get("roomId") or value.get("id") or "") != room_id
            ]
            if result_room is not None:
                snapshot_rooms.append(deepcopy(result_room))
            snapshot["rooms"] = snapshot_rooms
            snapshot["captureSchemaVersion"] = 2
            snapshot["captureRevision"] = int(snapshot.get("captureRevision") or 0) + 1
            job["snapshot"] = snapshot
            job["updated_at"] = now
            job["updated_by"] = actor_id

            result = {
                "operationId": operation_id,
                "action": normalized_action,
                "roomId": room_id,
                "revision": revision,
                "deleted": normalized_action == "DELETE",
                "room": result_room,
            }
            receipts[operation_id] = {
                "id": operation_id,
                "operation_id": operation_id,
                "request_hash": request_hash,
                "action": normalized_action,
                "workspace_id": workspace_id,
                "job_id": job_id,
                "room_id": room_id,
                "result": deepcopy(result),
                "status": "APPLIED",
                "source": "ROOMFLOW_CAPTURE",
                "created_at": now,
                "updated_at": now,
                "created_by": actor_id,
                "updated_by": actor_id,
            }
            metadata = (room or (existing or {}).get("room") or {}).get("scanMetadata") or {}
            audit_id = str(uuid.uuid4())
            operations["roomflow_capture_audit"][audit_id] = {
                "id": audit_id,
                "event": f"ROOMFLOW_CAPTURE_{normalized_action}",
                "workspace_id": workspace_id,
                "job_id": job_id,
                "room_id": room_id,
                "operation_id": operation_id,
                "revision": revision,
                "capture_mode": str(metadata.get("captureMode") or "unknown")[:80],
                "point_count": int(metadata.get("pointCount") or 0),
                "automatic_corrections": int(metadata.get("automaticCorrectionCount") or 0),
                "manual_corrections": int(metadata.get("manualCorrectionCount") or 0),
                "raw_capture_retained": False,
                "occurred_at": now,
                "source": "ROOMFLOW_CAPTURE",
                "created_at": now,
                "updated_at": now,
                "created_by": actor_id,
                "updated_by": actor_id,
            }
            self._save()
            return {"replayed": False, **deepcopy(result)}

    def save_upload(self, filename: str, content: bytes) -> tuple[str, Path]:
        safe_name = Path(filename or "document.pdf").name.replace("\x00", "")
        if not safe_name:
            safe_name = "document.pdf"
        file_id = str(uuid.uuid4())
        directory = self.upload_root / file_id
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / safe_name
        path.write_bytes(content)
        return file_id, path

    def upload_path(self, file_id: str, filename: str) -> Path:
        root = (self.upload_root / Path(file_id).name).resolve()
        path = (root / Path(filename).name).resolve()
        if root not in path.parents:
            raise ValueError("unsafe upload path")
        return path

    def clock_in(self, user_id: str, job_reference: str, note: str = "") -> dict[str, Any]:
        current = self.current_clock(user_id)
        if current:
            return current
        return self.create_record("time_entries", {
            "user_id": user_id,
            "job_reference": job_reference.strip(),
            "note": note.strip(),
            "clock_in": _now(),
            "clock_out": None,
            "status": "RUNNING",
        }, actor_id=user_id)

    def clock_out(self, user_id: str, note: str = "") -> dict[str, Any] | None:
        current = self.current_clock(user_id)
        if not current:
            return None
        started = parse_time(current.get("clock_in")) or utcnow()
        ended = utcnow()
        return self.update_record("time_entries", current["id"], {
            "clock_out": ended.isoformat(),
            "duration_seconds": max(0, int((ended - started).total_seconds())),
            "status": "COMPLETED",
            "note": note.strip() or current.get("note") or "",
        }, actor_id=user_id)

    def current_clock(self, user_id: str) -> dict[str, Any] | None:
        for entry in self.records("time_entries"):
            if entry.get("user_id") == user_id and entry.get("status") == "RUNNING":
                return entry
        return None

    # ------------------------------------------------------------------
    # Unified client-file matching and signed-document attachment
    # ------------------------------------------------------------------
    @staticmethod
    def _normalized_email(value: str | None) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _normalized_phone(value: str | None) -> str:
        digits = "".join(character for character in str(value or "") if character.isdigit())
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        return digits[-10:] if len(digits) >= 10 else digits

    @classmethod
    def _staff_phone(cls, value: str | None) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        digits = "".join(character for character in raw if character.isdigit())
        if len(digits) == 10:
            return f"+1{digits}"
        if len(digits) == 11 and digits.startswith("1"):
            return f"+{digits}"
        if raw.startswith("+") and 8 <= len(digits) <= 15:
            return f"+{digits}"
        raise ValueError("Enter the staff mobile number with area code and country code.")

    def find_contact(
        self,
        *,
        contact_id: str | None = None,
        external_contact_id: str | None = None,
        email: str | None = None,
        phone: str | None = None,
    ) -> dict[str, Any] | None:
        if contact_id:
            direct = self.record("contacts", str(contact_id))
            if direct:
                return direct

        external = str(external_contact_id or "").strip()
        email_key = self._normalized_email(email)
        phone_key = self._normalized_phone(phone)
        mappings = self.external_mappings("gauzy")
        mapped_local_ids = {
            key.split(":", 1)[1]
            for key, value in mappings.items()
            if key.startswith("contact:") and external and str(value) == external
        }
        for item in self.records("contacts"):
            item_id = str(item.get("id") or "")
            if item_id in mapped_local_ids:
                return item
            if external and external in {
                str(item.get("full_gauzy_id") or ""),
                str(item.get("provider_id") or ""),
                str(item.get("erp_contact_id") or ""),
                str(item.get("legacy_contact_id") or ""),
                str(item.get("customer_external_id") or ""),
                str(item.get("external_id") or ""),
            }:
                return item
            if email_key and self._normalized_email(item.get("email") or item.get("primaryEmail")) == email_key:
                return item
            if phone_key and self._normalized_phone(item.get("phone") or item.get("primaryPhone")) == phone_key:
                return item
        return None

    def ensure_workflow_client(
        self,
        *,
        customer: dict[str, Any],
        property_data: dict[str, Any] | None,
        external_contact_id: str | None,
        external_project_id: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        first_name = str(customer.get("first_name") or customer.get("firstName") or "").strip()
        last_name = str(customer.get("last_name") or customer.get("lastName") or "").strip()
        name = str(customer.get("name") or "").strip() or " ".join(
            value for value in (first_name, last_name) if value
        ).strip()
        email = str(customer.get("email") or customer.get("primaryEmail") or "").strip().lower()
        phone = str(customer.get("phone") or customer.get("primaryPhone") or "").strip()

        contact = self.find_contact(
            external_contact_id=external_contact_id,
            email=email,
            phone=phone,
        )
        if contact is None:
            identity_source = external_contact_id or email or self._normalized_phone(phone) or name or str(uuid.uuid4())
            contact_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"floodman-client:{identity_source}"))
            contact = self.create_record(
                "contacts",
                {
                    "id": contact_id,
                    "first_name": first_name,
                    "last_name": last_name,
                    "name": name or email or phone or "Floodman client",
                    "company": str(customer.get("company") or "").strip(),
                    "email": email,
                    "phone": phone,
                    "lead_source": "SIGNED_DOCUMENT_WORKFLOW",
                    "notes": "Created automatically when a Floodman document was completed.",
                    "status": "ACTIVE",
                    "full_gauzy_id": external_contact_id or None,
                    "erp_contact_id": external_contact_id or None,
                    "source": "FLOODMAN_SIGNING",
                    "created_by_name": "Josh Aldrich",
                    "creator_display": "Created by Josh Aldrich",
                },
                actor_id="floodman-signing",
            )
        else:
            updates: dict[str, Any] = {}
            if external_contact_id and not contact.get("full_gauzy_id"):
                updates["full_gauzy_id"] = external_contact_id
                updates["erp_contact_id"] = external_contact_id
            if updates and self.record("contacts", str(contact.get("id") or "")):
                contact = self.update_record(
                    "contacts",
                    str(contact["id"]),
                    updates,
                    actor_id="floodman-signing",
                )
        if external_contact_id:
            self.set_external_mapping("gauzy", f"contact:{contact['id']}", str(external_contact_id))

        property_record: dict[str, Any] | None = None
        property_data = dict(property_data or {})
        if property_data:
            candidates = [
                item
                for item in self.records("properties")
                if str(item.get("contact_id") or "") == str(contact.get("id") or "")
            ]
            external_project = str(external_project_id or "")
            street = str(
                property_data.get("street")
                or property_data.get("service_street")
                or (property_data.get("service_address") or {}).get("street")
                or ""
            ).strip()
            postal = str(
                property_data.get("postal_code")
                or property_data.get("service_postal_code")
                or (property_data.get("service_address") or {}).get("postal_code")
                or ""
            ).strip()
            for item in candidates:
                if external_project and external_project in {
                    str(item.get("full_gauzy_id") or ""),
                    str(item.get("erp_project_id") or ""),
                }:
                    property_record = item
                    break
                if street and str(item.get("service_street") or "").strip().lower() == street.lower():
                    if not postal or str(item.get("service_postal_code") or "").strip() == postal:
                        property_record = item
                        break
            if property_record is None and (street or external_project):
                identity_source = external_project or f"{contact['id']}|{street}|{postal}"
                property_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"floodman-property:{identity_source}"))
                address = property_data.get("service_address") or {}
                property_record = self.create_record(
                    "properties",
                    {
                        "id": property_id,
                        "contact_id": contact["id"],
                        "name": str(property_data.get("name") or property_data.get("property_name") or street or "Service property"),
                        "property_name": str(property_data.get("property_name") or property_data.get("name") or street or "Service property"),
                        "service_street": street,
                        "service_street2": str(property_data.get("street2") or property_data.get("service_street2") or address.get("street2") or ""),
                        "service_city": str(property_data.get("city") or property_data.get("service_city") or address.get("city") or ""),
                        "service_state": str(property_data.get("state") or property_data.get("service_state") or address.get("state") or ""),
                        "service_postal_code": postal,
                        "property_type": str(property_data.get("property_type") or "SERVICE_PROPERTY"),
                        "full_gauzy_id": external_project_id or None,
                        "erp_project_id": external_project_id or None,
                        "source": "FLOODMAN_SIGNING",
                        "created_by_name": "Josh Aldrich",
                        "creator_display": "Created by Josh Aldrich",
                    },
                    actor_id="floodman-signing",
                )
            if property_record and external_project_id:
                self.set_external_mapping("gauzy", f"property:{property_record['id']}", str(external_project_id))

        return contact, property_record

    def upsert_client_file(self, values: dict[str, Any]) -> dict[str, Any]:
        document_id = str(values.get("id") or values.get("workflow_document_id") or "").strip()
        if not document_id:
            raise ValueError("client file requires a document ID")
        existing = self.record("documents", document_id)
        payload = {
            **values,
            "id": document_id,
            "status": str(values.get("status") or "SIGNED").upper(),
            "source": str(values.get("source") or "FLOODMAN_SIGNING"),
            "immutable": True,
            "attached_to_client_file": True,
            "created_by_name": str(values.get("created_by_name") or "Josh Aldrich"),
            "creator_display": str(values.get("creator_display") or "Created by Josh Aldrich"),
        }
        if existing:
            return self.update_record("documents", document_id, payload, actor_id="floodman-signing")
        return self.create_record("documents", payload, actor_id="floodman-signing")

    # ------------------------------------------------------------------
    # Migration archive
    # ------------------------------------------------------------------
    def create_import(self, metadata: dict[str, Any], normalized: dict[str, Any], files: dict[str, bytes]) -> str:
        run_id = str(uuid.uuid4())
        run_dir = self.import_root / run_id
        files_dir = run_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=False)
        for name, content in files.items():
            relative = _safe_relative(name)
            destination = files_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        (run_dir / "normalized.json").write_text(
            json.dumps(normalized, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )
        run = {
            "id": run_id,
            "status": "PREVIEWED" if not metadata.get("errors") else "INVALID",
            "created_at": _now(),
            "updated_at": _now(),
            **metadata,
        }
        with self.lock:
            self._state["imports"].insert(0, run)
            self._state["imports"] = self._state["imports"][:100]
            self._state["checklist"]["import_reviewed"] = True
            self._state["last_notice"] = "Import bundle validated. Review it before committing."
            self._save()
        return run_id

    def list_imports(self) -> list[dict[str, Any]]:
        return self.snapshot()["imports"]

    def get_import(self, run_id: str) -> dict[str, Any] | None:
        for run in self.list_imports():
            if run.get("id") == run_id:
                return run
        return None

    def update_import(self, run_id: str, **values: Any) -> dict[str, Any]:
        with self.lock:
            for run in self._state["imports"]:
                if run.get("id") == run_id:
                    run.update(values)
                    run["updated_at"] = _now()
                    self._save()
                    return deepcopy(run)
        raise KeyError(run_id)

    def read_normalized(self, run_id: str) -> dict[str, Any]:
        path = self.import_root / run_id / "normalized.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def file_path(self, run_id: str, name: str) -> Path:
        relative = _safe_relative(name)
        root = (self.import_root / run_id / "files").resolve()
        path = (root / relative).resolve()
        if path != root and root not in path.parents:
            raise ValueError("unsafe import file path")
        return path

    def archive_import(self, run_id: str, normalized: dict[str, Any]) -> dict[str, int]:
        imported_at = _now()
        written: dict[str, int] = {}
        with self.lock:
            for kind, id_field in ARCHIVE_ID_FIELDS.items():
                target = self._state["archive"][kind]
                count = 0
                for raw in normalized.get(kind) or []:
                    record_id = str(raw.get(id_field) or "").strip()
                    if not record_id:
                        continue
                    record = {key: value for key, value in raw.items() if not key.startswith("_row")}
                    record["import_run_id"] = run_id
                    record["imported_at"] = imported_at
                    record["legacy_source"] = "townsquare"
                    record["import_mode"] = "HISTORICAL_ARCHIVE"
                    target[record_id] = record
                    count += 1
                written[kind] = count
            self._save()
        return written

    def archive_records(self, kind: str) -> list[dict[str, Any]]:
        if kind not in ARCHIVE_ID_FIELDS:
            raise KeyError(kind)
        values = self.snapshot()["archive"].get(kind) or {}
        return list(values.values())

    def archive_counts(self) -> dict[str, int]:
        snapshot = self.snapshot()["archive"]
        return {kind: len(snapshot.get(kind) or {}) for kind in ARCHIVE_ID_FIELDS}
