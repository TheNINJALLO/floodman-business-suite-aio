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
    "contacts", "properties", "estimates", "invoices", "payments", "documents", "notes", "time_entries", "tasks"
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
        "roomflow_url": "https://theninjallo.github.io/roomflow/",
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
        """Create or refresh a Floodman-module identity from a verified Gauzy account."""
        email_key = str(identity.get("email") or "").strip().lower()
        if not email_key:
            raise ValueError("Gauzy did not return an email address.")
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
                raise ValueError("A Gauzy administrator must create the first Floodman owner account.")
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
            self._state["last_notice"] = f"Gauzy member {email_key} connected to Floodman modules."
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

    def create_invite(self, name: str, email: str, role: str, created_by: str) -> tuple[dict[str, Any], str]:
        email_key = email.strip().lower()
        if self.user_by_email(email_key):
            raise ValueError("A member with that email already exists.")
        token = new_token("invite_")
        invite_id = str(uuid.uuid4())
        invite = {
            "id": invite_id,
            "name": name.strip(),
            "email": email_key,
            "role": role.strip().upper(),
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

    def update_user(self, user_id: str, *, role: str | None = None, status: str | None = None, password: str | None = None) -> dict[str, Any]:
        with self.lock:
            user = self._state["users"].get(user_id)
            if not user:
                raise KeyError(user_id)
            if user.get("role") == "OWNER" and status and status != "ACTIVE":
                raise ValueError("The primary owner cannot be disabled.")
            if role and user.get("role") != "OWNER":
                user["role"] = role.upper()
            if status:
                user["status"] = status.upper()
            if password:
                user["password_hash"] = hash_password(password)
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
