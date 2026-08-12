from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AccountFacts(StrictModel):
    """Coarse, non-identifying facts supplied to the classifier.

    Exact balances, invoice numbers, customer URLs, names, addresses, phone
    numbers, and provider identifiers remain inside the orchestrator. The AI
    service only decides which guarded application action is appropriate.
    """

    has_balance: bool
    is_past_due: bool
    status: str = Field(min_length=1, max_length=50)
    payment_terms: Literal["DUE_UPON_RECEIPT"] = "DUE_UPON_RECEIPT"


class ConversationItem(StrictModel):
    direction: Literal["INBOUND", "OUTBOUND", "INTERNAL"]
    body: str = Field(max_length=1000)


class ClassifyRequest(StrictModel):
    message_id: str = Field(min_length=1, max_length=100)
    customer_message: str = Field(min_length=1, max_length=3000)
    account: AccountFacts
    conversation: list[ConversationItem] = Field(default_factory=list, max_length=20)


class Decision(StrictModel):
    intent: Literal[
        "BALANCE_QUERY", "DUE_DATE_QUERY", "RESEND_LINK", "PAID_CLAIM", "CALLBACK_REQUEST",
        "PROMISE_TO_PAY", "APPROVED_FAQ", "DISPUTE_OR_SAFETY", "OTHER"
    ]
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    confidence: float = Field(ge=0, le=1)
    proposed_action: Literal[
        "REPORT_BALANCE", "REPORT_DUE_DATE", "RESEND_PAYMENT_LINK", "RESEND_INVOICE",
        "ACKNOWLEDGE_PAID_CLAIM", "CREATE_CALLBACK", "CREATE_PROMISE_TO_PAY",
        "ANSWER_APPROVED_FAQ", "PAUSE_AND_ESCALATE", "NO_ACTION"
    ]
    reply_draft: str = Field(default="", max_length=1500)
    human_review_required: bool
    promise_to_pay_date: str | None = Field(default=None, max_length=10)
    reasoning_summary: str = Field(default="", max_length=500)
    provider: str = Field(default="deterministic", max_length=50)
    model: str | None = Field(default=None, max_length=100)
