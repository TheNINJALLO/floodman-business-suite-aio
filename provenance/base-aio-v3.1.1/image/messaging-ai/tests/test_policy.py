from app.openai_client import redact_external_text
from app.policy import deterministic_decision
from app.schemas import AccountFacts, ClassifyRequest


def request(body: str) -> ClassifyRequest:
    return ClassifyRequest(
        message_id="m1",
        customer_message=body,
        account=AccountFacts(has_balance=True, is_past_due=True, status="PAST_DUE"),
    )


def test_balance_is_safe_read_only_action():
    result = deterministic_decision(request("How much do I owe?"))
    assert result.proposed_action == "REPORT_BALANCE"
    assert not result.human_review_required


def test_dispute_fails_closed():
    result = deterministic_decision(request("The work is incomplete and the amount is wrong"))
    assert result.proposed_action == "PAUSE_AND_ESCALATE"
    assert result.risk_level == "HIGH"


def test_explicit_iso_promise_date():
    result = deterministic_decision(request("I can pay on 2026-08-12"))
    assert result.proposed_action == "CREATE_PROMISE_TO_PAY"
    assert result.promise_to_pay_date == "2026-08-12"


def test_external_ai_redaction_removes_direct_identifiers():
    original = (
        "Invoice F-1042-FINAL is $2,850.00. Email me at josh@example.com, call (313) 555-1212, "
        "or use https://pay.example.test/p/secret-token on 2026-08-12."
    )
    redacted = redact_external_text(original)
    assert "F-1042-FINAL" not in redacted
    assert "$2,850.00" not in redacted
    assert "josh@example.com" not in redacted
    assert "313" not in redacted
    assert "secret-token" not in redacted
    assert "2026-08-12" in redacted
