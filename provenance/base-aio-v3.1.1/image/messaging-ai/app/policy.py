from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from .schemas import ClassifyRequest, Decision

HIGH_RISK = re.compile(
    r"\b(attorney|lawyer|lawsuit|court|lien|chargeback|dispute|refund|damaged?|incomplete|"
    r"not finished|wrong amount|overcharg\w*|insurance|complaint|police|regulator|wrong number|not the right person)\b",
    re.I,
)


def deterministic_decision(request: ClassifyRequest) -> Decision:
    body = request.customer_message.strip()
    lower = body.lower()
    if HIGH_RISK.search(body):
        return Decision(
            intent="DISPUTE_OR_SAFETY", risk_level="HIGH", confidence=0.99,
            proposed_action="PAUSE_AND_ESCALATE", human_review_required=True,
            reasoning_summary="Matched a protected dispute, legal, damage, refund, or workmanship category."
        )
    if any(word in lower for word in ("balance", "owe", "amount due", "how much")):
        return Decision(intent="BALANCE_QUERY", risk_level="LOW", confidence=0.97, proposed_action="REPORT_BALANCE", human_review_required=False)
    if any(word in lower for word in ("when is", "due date", "when due", "due?")):
        return Decision(intent="DUE_DATE_QUERY", risk_level="LOW", confidence=0.96, proposed_action="REPORT_DUE_DATE", human_review_required=False)
    if any(word in lower for word in ("resend", "send link", "payment link", "invoice link", "copy of invoice")):
        return Decision(intent="RESEND_LINK", risk_level="LOW", confidence=0.96, proposed_action="RESEND_PAYMENT_LINK", human_review_required=False)
    if any(word in lower for word in ("already paid", "i paid", "payment sent", "paid it")):
        return Decision(intent="PAID_CLAIM", risk_level="LOW", confidence=0.94, proposed_action="ACKNOWLEDGE_PAID_CLAIM", human_review_required=False)
    if any(word in lower for word in ("call me", "call back", "phone me", "speak to")):
        return Decision(intent="CALLBACK_REQUEST", risk_level="MEDIUM", confidence=0.96, proposed_action="CREATE_CALLBACK", human_review_required=True)
    iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", lower)
    if ("pay" in lower or "payment" in lower) and iso:
        return Decision(
            intent="PROMISE_TO_PAY", risk_level="LOW", confidence=0.94,
            proposed_action="CREATE_PROMISE_TO_PAY", human_review_required=False,
            promise_to_pay_date=iso.group(1),
        )
    if any(word in lower for word in ("why deposit", "receipt", "how do i pay", "square", "payment method")):
        return Decision(
            intent="APPROVED_FAQ", risk_level="LOW", confidence=0.95,
            proposed_action="ANSWER_APPROVED_FAQ", human_review_required=False,
            reply_draft=(
                "Floodman uses Square for secure payments. Your customer portal contains the current invoice, "
                "signed documents, payment links, and recorded balance. Reply CALL if you need office assistance."
            ),
        )
    return Decision(
        intent="OTHER", risk_level="MEDIUM", confidence=0.60,
        proposed_action="NO_ACTION", human_review_required=True,
        reasoning_summary="The message does not fit a safely automated account-service category."
    )
