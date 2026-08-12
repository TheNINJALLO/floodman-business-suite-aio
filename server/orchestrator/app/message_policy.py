from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

STOP_WORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit", "revoke", "optout", "opt out", "remove me", "do not text me", "don't text me", "no more texts"}
START_WORDS = {"start", "unstop", "subscribe", "yes"}
HELP_WORDS = {"help", "info"}

HIGH_RISK_PATTERNS = (
    r"\battorney\b", r"\blawyer\b", r"\blawsuit\b", r"\bcourt\b", r"\blien\b",
    r"\bchargeback\b", r"\bdispute\b", r"\brefund\b", r"\bdamage(?:d)?\b",
    r"\bincomplete\b", r"\bnot finished\b", r"\bwrong amount\b", r"\bovercharg",
    r"\binsurance\b", r"\bcomplaint\b", r"\bpolice\b", r"\bregulator\b",
    r"\bwrong number\b", r"\bnot the right person\b", r"\bdo not know (?:them|this person)\b",
)

ALLOWED_AUTO_ACTIONS = {
    "REPORT_BALANCE",
    "REPORT_DUE_DATE",
    "RESEND_PAYMENT_LINK",
    "RESEND_INVOICE",
    "ACKNOWLEDGE_PAID_CLAIM",
    "CREATE_CALLBACK",
    "CREATE_PROMISE_TO_PAY",
    "ANSWER_APPROVED_FAQ",
    "PAUSE_AND_ESCALATE",
    "NO_ACTION",
}


@dataclass(frozen=True, slots=True)
class KeywordDecision:
    kind: str
    normalized_body: str


def keyword_decision(body: str, provider_opt_out_type: str | None = None) -> KeywordDecision | None:
    normalized = re.sub(r"\s+", " ", (body or "").strip().lower())
    provider = (provider_opt_out_type or "").strip().upper()
    if provider in {"STOP", "START", "HELP"}:
        return KeywordDecision(provider, normalized)
    if normalized in STOP_WORDS:
        return KeywordDecision("STOP", normalized)
    if normalized in START_WORDS:
        return KeywordDecision("START", normalized)
    if normalized in HELP_WORDS:
        return KeywordDecision("HELP", normalized)
    return None


def requires_immediate_human(body: str) -> bool:
    lowered = (body or "").lower()
    return any(re.search(pattern, lowered) for pattern in HIGH_RISK_PATTERNS)


def immediate_hold_type(body: str) -> str:
    lowered = (body or "").lower()
    if re.search(r"\b(wrong number|not the right person|do not know (?:them|this person))\b", lowered):
        return "WRONG_NUMBER"
    if re.search(r"\b(attorney|lawyer|lawsuit|court|lien|regulator|police)\b", lowered):
        return "LEGAL"
    return "DISPUTE"


def enforce_ai_decision(
    decision: dict[str, Any],
    *,
    min_confidence: float,
    auto_low: bool,
    auto_medium: bool,
) -> dict[str, Any]:
    result = dict(decision)
    action = str(result.get("proposed_action") or "NO_ACTION").upper()
    risk = str(result.get("risk_level") or "HIGH").upper()
    confidence = float(result.get("confidence") or 0)
    human = bool(result.get("human_review_required", True))
    if action not in ALLOWED_AUTO_ACTIONS:
        action = "PAUSE_AND_ESCALATE"
        human = True
        risk = "HIGH"
    if confidence < min_confidence:
        human = True
    if risk == "HIGH":
        human = True
    elif risk == "MEDIUM" and not auto_medium:
        human = True
    elif risk == "LOW" and not auto_low:
        human = True
    if human and action not in {"PAUSE_AND_ESCALATE", "CREATE_CALLBACK", "NO_ACTION"}:
        action = "NO_ACTION"
    result.update(
        {
            "proposed_action": action,
            "risk_level": risk if risk in {"LOW", "MEDIUM", "HIGH"} else "HIGH",
            "confidence": max(0.0, min(confidence, 1.0)),
            "human_review_required": human,
        }
    )
    return result


def validate_promise_date(raw: str | None, *, today: date, max_days: int) -> date | None:
    if not raw:
        return None
    try:
        promised = date.fromisoformat(raw)
    except ValueError:
        return None
    if promised < today or promised > today + timedelta(days=max_days):
        return None
    return promised
