from __future__ import annotations

import importlib.util
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OFFICE_ROOT = ROOT / "office-console"
if str(OFFICE_ROOT) not in sys.path:
    sys.path.insert(0, str(OFFICE_ROOT))

from app.roomflow_supabase import (
    create_roomflow_workspace,
    ensure_roomflow_workspaces,
    select_roomflow_workspace,
)
from app.store import OfficeStore


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ai_calling = _load("floodman_ai_calling_contract", ROOT / "orchestrator" / "app" / "ai_calling.py")
security = _load("floodman_orchestrator_security", ROOT / "orchestrator" / "app" / "security.py")


def projection(provider_call_id: str, workspace_id: str, *, sequence: int = 0, phone: str = "+12315550110") -> dict:
    ids = ai_calling.stable_projection_ids("deterministic", provider_call_id)
    return {
        "intake_id": ids["intake_id"],
        "organization_id": "fictional-floodman-org",
        "workspace_id": workspace_id,
        "provider": "deterministic",
        "provider_call_id": provider_call_id,
        "event_type": "call-started" if sequence == 0 else "caller-identified",
        "event_sequence": sequence,
        "status": "ACTIVE",
        "occurred_at": datetime(2026, 9, 8, 15, sequence, tzinfo=UTC).isoformat(),
        "started_at": datetime(2026, 9, 8, 15, 0, tzinfo=UTC).isoformat(),
        "ended_at": None,
        "caller": {
            "name": "Jordan Example",
            "first_name": "Jordan",
            "last_name": "Example",
            "company": "",
            "email": "jordan@example.test",
            "phone": phone,
            "phone_e164": phone,
            "phone_verified": True,
        },
        "property": {
            "name": "Example residence",
            "property_type": "Residential",
            "street": "100 Fictional Avenue",
            "city": "Traverse City",
            "state": "MI",
            "postal_code": "49684",
            "country": "US",
            "insurer": "",
            "claim_number": "",
        },
        "service_reason": "Basement water inspection",
        "summary": "Caller reports water near a fictional basement wall and requests an inspection.",
        "requested_services": ["Inspection"],
        "urgency": "PRIORITY",
        "appointment": {"requested": True, "requested_window": "weekday afternoon", "confirmed": False, "appointment_id": ""},
        "consent": {"sms_status": "UNKNOWN", "email_status": "UNKNOWN", "disclosure_version": "", "evidence_id": ""},
        "transcript_available": True,
        "transcript_reference": "lab://fictional/transcript",
        "failure_reason": "",
        "review_reasons": [],
        "proposed_ids": {key: value for key, value in ids.items() if key != "intake_id"},
    }


def run() -> None:
    # Provider contract, replay identity, event order, and failure fallback.
    event_payload = {
        "provider": "deterministic",
        "provider_call_id": "fictional-call-contract",
        "event_id": "event-0",
        "event_type": "call-started",
        "event_sequence": 0,
        "organization_id": "fictional-floodman-org",
        "workspace_id": "fictional-workspace",
        "occurred_at": "2026-09-08T15:00:00Z",
        "caller": {"phone": "+12315550110"},
    }
    event = ai_calling.DeterministicAiCallingProvider().normalize(event_payload)
    assert ai_calling.event_dedupe_key(event) == ai_calling.event_dedupe_key(event)
    assert "fictional-call-contract:call-started" in ai_calling.event_dedupe_key(event)
    assert ai_calling.event_order_decision(1, event) == "STALE"
    stable_ids = ai_calling.stable_projection_ids(event.provider, event.provider_call_id)
    assert stable_ids == ai_calling.stable_projection_ids(event.provider, event.provider_call_id)
    assert len(stable_ids.values()) == len(set(stable_ids.values()))
    for sequence, event_type in enumerate(
        ("call-started", "caller-identified", "transcript-updated", "call-ended"),
    ):
        candidate = {
            **event_payload,
            "event_id": f"event-{event_type}",
            "event_type": event_type,
            "event_sequence": sequence,
        }
        if event_type == "transcript-updated":
            candidate.update({"transcript_available": True, "summary": "Fictional structured call update."})
        classified = ai_calling.AiCallEvent.model_validate(candidate)
        expected = "COMPLETED" if event_type == "call-ended" else "ACTIVE"
        assert ai_calling.next_call_status(classified) == expected
    failed = ai_calling.AiCallEvent.model_validate({
        **event_payload,
        "event_id": "event-failed",
        "event_type": "call-failed",
        "event_sequence": 2,
        "failure_reason": "fictional provider timeout",
    })
    assert ai_calling.next_call_status(failed) == "REVIEW_REQUIRED"

    # Invalid signatures fail closed before any event interpretation.
    secret = b"1" * 32
    body = b'{"fictional":true}'
    headers = security.internal_headers("call-v1", secret, body, timestamp=2_000_000_000)
    assert security.verify_internal_request(headers, body, {"call-v1": secret}, 300, now=2_000_000_000) == "call-v1"
    bad_headers = {**headers, "x-floodman-signature": "invalid"}
    try:
        security.verify_internal_request(bad_headers, body, {"call-v1": secret}, 300, now=2_000_000_000)
        raise AssertionError("invalid signature was accepted")
    except security.AuthenticationError:
        pass

    with tempfile.TemporaryDirectory(prefix="floodman-ai-call-intake-") as temp:
        store = OfficeStore(temp)
        owner = store.create_owner("Fictional Owner", "owner@example.test", "Fictional-Password-2026!")
        _invite, invite_token = store.create_invite(
            "Second Workspace Viewer",
            "viewer@example.test",
            "VIEWER",
            owner["id"],
        )
        viewer_user = store.accept_invite(invite_token, "Fictional-Viewer-2026!")
        workspace_a = ensure_roomflow_workspaces(store, actor_id=owner["id"])[0]
        workspace_b = create_roomflow_workspace(
            store,
            name="Fictional Second Workspace",
            timezone="America/Detroit",
            user_id=viewer_user["id"],
            actor_id=owner["id"],
        )
        select_roomflow_workspace(store, owner["id"], workspace_a["id"], actor_id=owner["id"])
        select_roomflow_workspace(store, viewer_user["id"], workspace_b["id"], actor_id=viewer_user["id"])

        known = store.create_record(
            "contacts",
            {
                "workspace_id": workspace_a["id"],
                "name": "Jordan Existing",
                "email": "existing@example.test",
                "phone": "+12315550111",
                "source": "TEST_FIXTURE",
            },
            actor_id=owner["id"],
        )
        known_result = store.project_call_intake(
            projection("fictional-known", workspace_a["id"], phone="+12315550111")
        )
        assert known_result["customer_id"] == known["id"], "known caller was not linked by one exact phone match"
        assert known_result["property_id"] and known_result["roomflow_job_id"] and known_result["estimate_id"]
        estimate = store.record("estimates", known_result["estimate_id"])
        assert estimate and estimate["publication_status"] == "UNPUBLISHED"
        assert estimate["pricing_status"] == "NOT_PRICED" and estimate["total_cents"] == 0
        assert estimate["line_items"] == [] and estimate["sections"] == []
        roomflow = store.record("roomflow_jobs", known_result["roomflow_job_id"])
        assert roomflow and roomflow["measurement_status"] == "NOT_CAPTURED"
        assert roomflow["snapshot"]["rooms"] == [] and roomflow["snapshot"]["capturedMeasurements"] == []
        note = store.record("notes", known_result["note_id"])
        assert note and note["entity_type"] == "CONTACT" and note["entity_id"] == known["id"]
        assert note["note_type"] == "CALL" and "basement wall" in note["body"]

        unverified = projection("fictional-unverified", workspace_a["id"], phone="+12315550111")
        unverified["caller"]["phone_verified"] = False
        unverified_result = store.project_call_intake(unverified)
        assert unverified_result["customer_id"] != known["id"], "unverified caller ID linked an existing customer"

        # Invalid projections fail before any part of the record graph is committed.
        before_invalid = store.snapshot()["operations"]
        invalid_projection = projection("fictional-invalid-projection", workspace_a["id"])
        del invalid_projection["proposed_ids"]["task_id"]
        try:
            store.project_call_intake(invalid_projection)
            raise AssertionError("projection without stable task ID was accepted")
        except ValueError:
            pass
        assert store.snapshot()["operations"] == before_invalid, "failed projection changed local business data"
        assert known_result["task_id"]
        assert known_result["appointment_id"] and store.record("appointments", known_result["appointment_id"])["status"] == "REQUESTED_UNCONFIRMED"

        # The selected second workspace user does not receive or read workspace A call data.
        viewer_notifications = [
            value for value in store.records("notifications")
            if str(value.get("user_id") or "") == viewer_user["id"]
        ]
        assert not viewer_notifications, "cross-workspace call notification leaked to another selected workspace"

        replay = store.project_call_intake(projection("fictional-known", workspace_a["id"], phone="+12315550111"))
        assert replay["replayed"] is True
        assert len([value for value in store.records("estimates") if value["id"] == known_result["estimate_id"]]) == 1
        assert len([value for value in store.records("notes") if value["id"] == known_result["note_id"]]) == 1

        new_result = store.project_call_intake(projection("fictional-new", workspace_a["id"], phone="+12315550112"))
        assert store.record("contacts", new_result["customer_id"])["source"] == "AI_CALLING"

        for suffix in ("one", "two"):
            store.create_record(
                "contacts",
                {
                    "workspace_id": workspace_a["id"],
                    "name": f"Ambiguous {suffix}",
                    "email": f"ambiguous-{suffix}@example.test",
                    "phone": "+12315550113",
                    "source": "TEST_FIXTURE",
                },
                actor_id=owner["id"],
            )
        ambiguous = store.project_call_intake(
            projection("fictional-ambiguous", workspace_a["id"], phone="+12315550113")
        )
        assert ambiguous["review_status"] == "REVIEW_REQUIRED"
        assert "AMBIGUOUS_CUSTOMER_MATCH" in ambiguous["review_reasons"]
        assert not ambiguous["customer_id"] and not ambiguous["estimate_id"]

        # A new store instance proves queue and linked records survive restart.
        restarted = OfficeStore(temp)
        assert restarted.record("call_intakes", known_result["id"])
        assert restarted.record("estimates", known_result["estimate_id"])["total_cents"] == 0

    ui_source = (ROOT / "office-console" / "app" / "ui.py").read_text(encoding="utf-8")
    assert "role='dialog'" in ui_source and "data-call-intake-dismiss" in ui_source
    assert "EventSource('/office/api/call-intakes/events')" in ui_source
    assert "sessionStorage.setItem('floodmanDismissedCallIntake'" in ui_source
    print("Floodman AI call intake provider, linkage, isolation, safety, and persistence smoke test passed")


if __name__ == "__main__":
    run()
