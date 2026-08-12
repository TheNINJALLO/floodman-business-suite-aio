from __future__ import annotations

from enum import StrEnum


class WorkflowState(StrEnum):
    DRAFT = "DRAFT"
    QUEUED = "QUEUED"
    ESTIMATE_SYNCED = "ESTIMATE_SYNCED"
    AUTHORIZATION_SENT = "AUTHORIZATION_SENT"
    AUTHORIZATION_SIGNED = "AUTHORIZATION_SIGNED"
    DEPOSIT_PUBLISHED = "DEPOSIT_PUBLISHED"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    IN_PROGRESS = "IN_PROGRESS"
    CHANGE_ORDER_PENDING = "CHANGE_ORDER_PENDING"
    COMPLETION_SENT = "COMPLETION_SENT"
    COMPLETION_SIGNED = "COMPLETION_SIGNED"
    FINAL_PAYMENT_DUE = "FINAL_PAYMENT_DUE"
    PAID = "PAID"
    CLOSED = "CLOSED"
    PAYMENT_REVIEW = "PAYMENT_REVIEW"
    FAILED = "FAILED"


_ALLOWED: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.DRAFT: {WorkflowState.QUEUED, WorkflowState.FAILED},
    WorkflowState.QUEUED: {WorkflowState.ESTIMATE_SYNCED, WorkflowState.FAILED},
    WorkflowState.ESTIMATE_SYNCED: {WorkflowState.AUTHORIZATION_SENT, WorkflowState.QUEUED, WorkflowState.FAILED},
    WorkflowState.AUTHORIZATION_SENT: {WorkflowState.AUTHORIZATION_SIGNED, WorkflowState.FAILED},
    WorkflowState.AUTHORIZATION_SIGNED: {WorkflowState.DEPOSIT_PUBLISHED, WorkflowState.FAILED},
    WorkflowState.DEPOSIT_PUBLISHED: {
        WorkflowState.DEPOSIT_PAID, WorkflowState.PAID, WorkflowState.PAYMENT_REVIEW, WorkflowState.FAILED
    },
    WorkflowState.DEPOSIT_PAID: {
        WorkflowState.IN_PROGRESS, WorkflowState.CHANGE_ORDER_PENDING, WorkflowState.PAID,
        WorkflowState.PAYMENT_REVIEW, WorkflowState.FAILED
    },
    WorkflowState.IN_PROGRESS: {
        WorkflowState.CHANGE_ORDER_PENDING, WorkflowState.COMPLETION_SENT, WorkflowState.PAID,
        WorkflowState.PAYMENT_REVIEW, WorkflowState.FAILED
    },
    WorkflowState.CHANGE_ORDER_PENDING: {
        WorkflowState.IN_PROGRESS, WorkflowState.COMPLETION_SENT, WorkflowState.PAYMENT_REVIEW, WorkflowState.FAILED
    },
    WorkflowState.COMPLETION_SENT: {WorkflowState.COMPLETION_SIGNED, WorkflowState.IN_PROGRESS, WorkflowState.PAID, WorkflowState.FAILED},
    WorkflowState.COMPLETION_SIGNED: {
        WorkflowState.FINAL_PAYMENT_DUE, WorkflowState.PAID, WorkflowState.PAYMENT_REVIEW, WorkflowState.FAILED
    },
    WorkflowState.FINAL_PAYMENT_DUE: {WorkflowState.PAID, WorkflowState.PAYMENT_REVIEW, WorkflowState.FAILED},
    WorkflowState.PAID: {WorkflowState.CLOSED, WorkflowState.COMPLETION_SENT, WorkflowState.PAYMENT_REVIEW},
    WorkflowState.CLOSED: {WorkflowState.PAYMENT_REVIEW},
    WorkflowState.PAYMENT_REVIEW: {
        WorkflowState.DEPOSIT_PUBLISHED, WorkflowState.DEPOSIT_PAID, WorkflowState.IN_PROGRESS,
        WorkflowState.FINAL_PAYMENT_DUE, WorkflowState.PAID, WorkflowState.FAILED
    },
    WorkflowState.FAILED: {WorkflowState.QUEUED, WorkflowState.PAYMENT_REVIEW},
}


class InvalidTransition(ValueError):
    pass


class StartWorkDecision(StrEnum):
    READY = "READY"
    REPAIR_DEPOSIT_STATE_AND_READY = "REPAIR_DEPOSIT_STATE_AND_READY"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    ALREADY_STARTED = "ALREADY_STARTED"
    BLOCKED = "BLOCKED"


_START_ALREADY_ACTIVE = {
    WorkflowState.IN_PROGRESS,
    WorkflowState.CHANGE_ORDER_PENDING,
    WorkflowState.COMPLETION_SENT,
    WorkflowState.COMPLETION_SIGNED,
    WorkflowState.FINAL_PAYMENT_DUE,
    WorkflowState.PAID,
    WorkflowState.CLOSED,
}


def start_work_decision(
    current: str | WorkflowState,
    *,
    deposit_cents: int | None = None,
    recorded_paid_cents: int | None = None,
) -> StartWorkDecision:
    """Classify a Start Work request without mutating workflow state.

    Square webhook acceptance and outbox reconciliation are asynchronous. A job can
    briefly remain ``DEPOSIT_PUBLISHED`` immediately after payment. When the caller
    supplies ledger values, a fully recorded deposit may safely repair that lagging
    state. Calls without ledger values retain the conservative pending decision.
    """
    current_state = WorkflowState(current)
    if current_state == WorkflowState.DEPOSIT_PAID:
        return StartWorkDecision.READY
    if current_state == WorkflowState.DEPOSIT_PUBLISHED:
        if deposit_cents is not None and recorded_paid_cents is not None:
            required = max(0, int(deposit_cents))
            recorded = max(0, int(recorded_paid_cents))
            if recorded >= required:
                return StartWorkDecision.REPAIR_DEPOSIT_STATE_AND_READY
        return StartWorkDecision.PAYMENT_PENDING
    if current_state == WorkflowState.AUTHORIZATION_SIGNED:
        return StartWorkDecision.PAYMENT_PENDING
    if current_state in _START_ALREADY_ACTIVE:
        return StartWorkDecision.ALREADY_STARTED
    return StartWorkDecision.BLOCKED


def assert_transition(current: str | WorkflowState, target: str | WorkflowState) -> None:
    current_state = WorkflowState(current)
    target_state = WorkflowState(target)
    if current_state == target_state:
        return
    if target_state not in _ALLOWED[current_state]:
        raise InvalidTransition(f"Workflow transition {current_state} -> {target_state} is not allowed")
