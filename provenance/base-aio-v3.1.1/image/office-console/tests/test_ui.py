from __future__ import annotations

from app.ui import layout, money_cents, progress


def test_setup_progress_and_layout() -> None:
    checklist = {
        "owner_created": False,
        "profile_saved": True,
        "connections_tested": True,
        "import_reviewed": False,
        "legal_reviewed": False,
        "messaging_reviewed": False,
    }
    assert progress(checklist) == (2, 6, 33)
    page = layout("Setup", "<p>Body</p>", active="setup", release="test")
    assert "Floodman Office" in page
    assert "LOCAL BUSINESS STAGING" in page
    assert money_cents(12345) == "$123.45"
