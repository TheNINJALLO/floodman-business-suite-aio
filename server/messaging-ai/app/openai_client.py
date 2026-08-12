from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .config import Settings
from .knowledge import load_approved_knowledge
from .schemas import ClassifyRequest, Decision



URL_RE = re.compile(r"https?://[^\s<>()]+", re.I)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)")
MONEY_RE = re.compile(r"(?<!\w)(?:USD\s*)?\$\s?\d[\d,]*(?:\.\d{1,2})?|\b\d[\d,]*(?:\.\d{1,2})?\s?(?:USD|dollars?)\b", re.I)
INVOICE_RE = re.compile(r"\b(?:F-\d+(?:-[A-Z0-9]+)*|invoice\s*(?:number|no\.?|#)?\s*[:#-]?\s*[A-Z0-9][A-Z0-9-]{1,})\b", re.I)


def redact_external_text(value: str) -> str:
    """Remove direct account identifiers before an optional external AI call."""

    text = URL_RE.sub("[SECURE_LINK]", value or "")
    text = EMAIL_RE.sub("[EMAIL]", text)
    text = PHONE_RE.sub("[PHONE]", text)
    text = MONEY_RE.sub("[AMOUNT]", text)
    text = INVOICE_RE.sub("[INVOICE_ID]", text)
    return text[:3000]

DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "intent", "risk_level", "confidence", "proposed_action", "reply_draft",
        "human_review_required", "promise_to_pay_date", "reasoning_summary", "provider", "model"
    ],
    "properties": {
        "intent": {"type": "string", "enum": ["BALANCE_QUERY","DUE_DATE_QUERY","RESEND_LINK","PAID_CLAIM","CALLBACK_REQUEST","PROMISE_TO_PAY","APPROVED_FAQ","DISPUTE_OR_SAFETY","OTHER"]},
        "risk_level": {"type": "string", "enum": ["LOW","MEDIUM","HIGH"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "proposed_action": {"type": "string", "enum": ["REPORT_BALANCE","REPORT_DUE_DATE","RESEND_PAYMENT_LINK","RESEND_INVOICE","ACKNOWLEDGE_PAID_CLAIM","CREATE_CALLBACK","CREATE_PROMISE_TO_PAY","ANSWER_APPROVED_FAQ","PAUSE_AND_ESCALATE","NO_ACTION"]},
        "reply_draft": {"type": "string", "maxLength": 1500},
        "human_review_required": {"type": "boolean"},
        "promise_to_pay_date": {"type": ["string", "null"]},
        "reasoning_summary": {"type": "string", "maxLength": 500},
        "provider": {"type": "string"},
        "model": {"type": ["string", "null"]},
    },
}

SYSTEM = """You triage transactional customer SMS for Floodman, a property-services company.
You are not a debt collector, lawyer, payment processor, or account ledger.
Never change, negotiate, forgive, discount, threaten, add fees, issue refunds, take a payment,
or claim payment succeeded. Money and dates in ACCOUNT FACTS are read-only verified facts.
Any dispute, workmanship complaint, damage claim, refund, chargeback, insurance issue, legal
language, angry threat, ambiguous request, or request to alter terms requires PAUSE_AND_ESCALATE.
Only answer approved FAQs from APPROVED KNOWLEDGE. Keep reply drafts factual and under 600 chars.
A promise-to-pay action requires an explicit unambiguous ISO date within the supplied message.
"""


def _output_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                return content["text"]
    raise RuntimeError("OpenAI response did not contain structured output text")


class OpenAIClassifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.Client(
            base_url=settings.openai_base_url,
            timeout=httpx.Timeout(float(settings.openai_timeout_seconds), connect=10.0),
            verify=settings.openai_verify_tls,
            headers={"authorization": f"Bearer {settings.openai_api_key}", "content-type": "application/json"},
        )
        self.knowledge = load_approved_knowledge()

    def close(self) -> None:
        self.client.close()

    def classify(self, request: ClassifyRequest) -> Decision:
        facts = request.account.model_dump(mode="json")
        history = [
            {"direction": item.direction, "body": redact_external_text(item.body)}
            for item in request.conversation[-12:]
        ]
        user = json.dumps(
            {"ACCOUNT FACTS": facts, "CUSTOMER MESSAGE": redact_external_text(request.customer_message), "RECENT CONVERSATION": history, "APPROVED KNOWLEDGE": self.knowledge},
            separators=(",", ":"), ensure_ascii=False,
        )
        response = self.client.post(
            "/responses",
            json={
                "model": self.settings.openai_model,
                "store": False,
                "input": [
                    {"role": "system", "content": [{"type": "input_text", "text": SYSTEM}]},
                    {"role": "user", "content": [{"type": "input_text", "text": user}]},
                ],
                "text": {"format": {"type": "json_schema", "name": "floodman_message_decision", "strict": True, "schema": DECISION_SCHEMA}},
            },
        )
        response.raise_for_status()
        decision = Decision.model_validate_json(_output_text(response.json()))
        return decision.model_copy(update={"provider": "openai", "model": self.settings.openai_model})
