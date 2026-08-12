from datetime import date

from app.message_policy import enforce_ai_decision, keyword_decision, requires_immediate_human, validate_promise_date


def test_stop_start_help_bypass_ai() -> None:
    assert keyword_decision(" STOP ").kind == "STOP"
    assert keyword_decision("anything", "START").kind == "START"
    assert keyword_decision("help").kind == "HELP"


def test_disputes_and_legal_language_require_human() -> None:
    assert requires_immediate_human("The work is incomplete and I want a refund")
    assert requires_immediate_human("My attorney will call")
    assert not requires_immediate_human("Please resend my payment link")


def test_unknown_or_low_confidence_ai_action_fails_closed() -> None:
    decision = enforce_ai_decision(
        {
            "proposed_action": "ISSUE_REFUND",
            "risk_level": "LOW",
            "confidence": 0.99,
            "human_review_required": False,
        },
        min_confidence=0.9,
        auto_low=True,
        auto_medium=False,
    )
    assert decision["proposed_action"] == "PAUSE_AND_ESCALATE"
    assert decision["human_review_required"] is True


def test_promise_date_must_be_current_and_within_policy() -> None:
    today = date(2026, 8, 4)
    assert validate_promise_date("2026-08-12", today=today, max_days=14) == date(2026, 8, 12)
    assert validate_promise_date("2026-09-01", today=today, max_days=14) is None
    assert validate_promise_date("Friday", today=today, max_days=14) is None
