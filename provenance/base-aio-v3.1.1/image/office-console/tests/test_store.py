from __future__ import annotations

from app.store import OfficeStore


def test_profile_checklist_and_connection_plan_persist(tmp_path) -> None:
    store = OfficeStore(str(tmp_path))
    store.update_profile({"company_name": "Floodman Test", "office_email": "office@example.com"})
    store.update_checklist({"legal_reviewed": True})
    store.update_link_config({"square_mode": "SANDBOX", "square_location_id": "L123"})

    reloaded = OfficeStore(str(tmp_path))
    assert reloaded.profile()["company_name"] == "Floodman Test"
    assert reloaded.checklist()["profile_saved"] is True
    assert reloaded.checklist()["legal_reviewed"] is True
    assert reloaded.link_config()["square_mode"] == "SANDBOX"
    assert reloaded.link_config()["square_location_id"] == "L123"


def test_import_record_files_and_archive_persist(tmp_path) -> None:
    store = OfficeStore(str(tmp_path))
    normalized = {
        "contacts": [{"legacy_contact_id": "1"}],
        "properties": [{"legacy_property_id": "p1"}],
        "estimates": [],
        "estimate_lines": [],
        "invoices": [],
        "payments": [],
        "documents": [{"legacy_document_id": "d1", "file_path": "exports/doc.pdf"}],
        "notes": [{"legacy_note_id": "n1", "note": "Test"}],
    }
    run_id = store.create_import(
        {"counts": {"contacts": 1}, "totals": {}, "errors": [], "warnings": [], "valid": True},
        normalized,
        {"contacts.csv": b"legacy_contact_id\n1\n", "exports/doc.pdf": b"pdf"},
    )
    store.archive_import(run_id, normalized)
    assert store.get_import(run_id)["status"] == "PREVIEWED"
    assert store.file_path(run_id, "exports/doc.pdf").read_bytes() == b"pdf"

    reloaded = OfficeStore(str(tmp_path))
    assert reloaded.get_import(run_id) is not None
    assert reloaded.archive_counts()["contacts"] == 1
    assert reloaded.archive_counts()["properties"] == 1
    assert reloaded.archive_counts()["documents"] == 1
    assert reloaded.archive_counts()["notes"] == 1


def test_import_file_path_rejects_traversal(tmp_path) -> None:
    store = OfficeStore(str(tmp_path))
    for value in ("../secret.txt", "/etc/passwd", "..\\secret.txt"):
        try:
            store.file_path("run", value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe path was accepted: {value}")


def test_owner_invite_role_and_session_persist(tmp_path) -> None:
    store = OfficeStore(str(tmp_path))
    owner = store.create_owner("Primary Owner", "owner@example.com", "OwnerPassword123!")
    assert store.authenticate("owner@example.com", "OwnerPassword123!")["role"] == "OWNER"
    token = store.create_session(owner["id"])
    assert store.user_for_session(token)["email"] == "owner@example.com"

    invite, raw_token = store.create_invite("Manager", "manager@example.com", "OFFICE_MANAGER", owner["id"])
    assert invite["status"] == "PENDING"
    manager = store.accept_invite(raw_token, "ManagerPassword123!")
    assert manager["role"] == "OFFICE_MANAGER"
    assert store.authenticate("manager@example.com", "ManagerPassword123!")["id"] == manager["id"]

    reloaded = OfficeStore(str(tmp_path))
    assert len(reloaded.list_users()) == 2
    assert reloaded.get_user(owner["id"])["role"] == "OWNER"


def test_verified_gauzy_members_are_provisioned_without_storing_passwords(tmp_path) -> None:
    store = OfficeStore(str(tmp_path))
    owner = store.upsert_gauzy_user(
        {
            "email": "admin@ever.co",
            "name": "Gauzy Administrator",
            "gauzy_user_id": "gauzy-user-1",
            "gauzy_employee_id": "",
            "gauzy_role": "SUPER_ADMIN",
            "suggested_office_role": "ADMIN",
            "is_gauzy_admin": True,
        }
    )
    assert owner["role"] == "OWNER"
    assert owner["auth_source"] == "GAUZY"
    assert owner["password_hash"] == ""

    technician = store.upsert_gauzy_user(
        {
            "email": "employee@ever.co",
            "name": "Gauzy Employee",
            "gauzy_user_id": "gauzy-user-2",
            "gauzy_employee_id": "employee-2",
            "gauzy_role": "EMPLOYEE",
            "suggested_office_role": "TECHNICIAN",
            "is_gauzy_admin": False,
        }
    )
    assert technician["role"] == "TECHNICIAN"
    assert technician["password_hash"] == ""
    assert store.user_for_session(store.create_session(technician["id"]))["email"] == "employee@ever.co"


def test_gauzy_link_does_not_escalate_existing_local_role(tmp_path) -> None:
    store = OfficeStore(str(tmp_path))
    owner = store.create_owner("Primary Owner", "owner@example.com", "OwnerPassword123!")
    invite, token = store.create_invite("Viewer", "viewer@example.com", "VIEWER", owner["id"])
    assert invite["status"] == "PENDING"
    viewer = store.accept_invite(token, "ViewerPassword123!")

    linked = store.upsert_gauzy_user(
        {
            "email": "viewer@example.com",
            "name": "Viewer",
            "gauzy_user_id": "gauzy-viewer",
            "gauzy_employee_id": "gauzy-employee-viewer",
            "gauzy_role": "ADMIN",
            "suggested_office_role": "ADMIN",
            "is_gauzy_admin": True,
        }
    )
    assert linked["id"] == viewer["id"]
    assert linked["role"] == "VIEWER"
    assert linked["auth_source"] == "LOCAL_AND_GAUZY"
    assert store.authenticate("viewer@example.com", "ViewerPassword123!")["id"] == viewer["id"]


def test_first_gauzy_identity_must_be_an_administrator(tmp_path) -> None:
    store = OfficeStore(str(tmp_path))
    try:
        store.upsert_gauzy_user(
            {
                "email": "employee@ever.co",
                "name": "Employee",
                "gauzy_role": "EMPLOYEE",
                "suggested_office_role": "TECHNICIAN",
                "is_gauzy_admin": False,
            }
        )
    except ValueError as exc:
        assert "administrator" in str(exc).lower()
    else:
        raise AssertionError("A non-administrator became the first Floodman owner")


def test_crud_upload_and_time_clock_persist(tmp_path) -> None:
    store = OfficeStore(str(tmp_path))
    owner = store.create_owner("Primary Owner", "owner@example.com", "OwnerPassword123!")
    contact = store.create_record("contacts", {"name": "Jane Customer"}, actor_id=owner["id"])
    updated = store.update_record("contacts", contact["id"], {"phone": "+13135550199"}, actor_id=owner["id"])
    assert updated["phone"] == "+13135550199"
    file_id, path = store.save_upload("authorization.pdf", b"%PDF-1.4\n%%EOF")
    assert store.upload_path(file_id, "authorization.pdf").read_bytes() == path.read_bytes()

    entry = store.clock_in(owner["id"], "JOB-1", "Site visit")
    assert entry["status"] == "RUNNING"
    stopped = store.clock_out(owner["id"], "Complete")
    assert stopped["status"] == "COMPLETED"
    assert store.current_clock(owner["id"]) is None

    reloaded = OfficeStore(str(tmp_path))
    assert reloaded.record("contacts", contact["id"])["phone"] == "+13135550199"
    assert len(reloaded.records("time_entries")) == 1
