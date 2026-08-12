import pytest

from app.state_machine import (
    InvalidTransition, StartWorkDecision, WorkflowState, assert_transition, start_work_decision,
)


def test_happy_path_transitions() -> None:
    path = [
        WorkflowState.QUEUED,
        WorkflowState.ESTIMATE_SYNCED,
        WorkflowState.AUTHORIZATION_SENT,
        WorkflowState.AUTHORIZATION_SIGNED,
        WorkflowState.DEPOSIT_PUBLISHED,
        WorkflowState.DEPOSIT_PAID,
        WorkflowState.IN_PROGRESS,
        WorkflowState.COMPLETION_SENT,
        WorkflowState.COMPLETION_SIGNED,
        WorkflowState.FINAL_PAYMENT_DUE,
        WorkflowState.PAID,
        WorkflowState.CLOSED,
    ]
    for current, target in zip(path, path[1:]):
        assert_transition(current, target)


def test_cannot_bill_before_authorization() -> None:
    with pytest.raises(InvalidTransition):
        assert_transition(WorkflowState.ESTIMATE_SYNCED, WorkflowState.DEPOSIT_PUBLISHED)


def test_start_work_waits_while_deposit_webhook_is_pending() -> None:
    assert start_work_decision(
        WorkflowState.DEPOSIT_PUBLISHED, deposit_cents=30_000, recorded_paid_cents=0
    ) == StartWorkDecision.PAYMENT_PENDING


def test_start_work_repairs_lagging_deposit_state_when_ledger_is_paid() -> None:
    assert start_work_decision(
        WorkflowState.DEPOSIT_PUBLISHED, deposit_cents=30_000, recorded_paid_cents=30_000
    ) == StartWorkDecision.REPAIR_DEPOSIT_STATE_AND_READY


def test_start_work_is_idempotent_after_work_has_started() -> None:
    for state in (
        WorkflowState.IN_PROGRESS,
        WorkflowState.CHANGE_ORDER_PENDING,
        WorkflowState.COMPLETION_SENT,
        WorkflowState.COMPLETION_SIGNED,
        WorkflowState.FINAL_PAYMENT_DUE,
        WorkflowState.PAID,
        WorkflowState.CLOSED,
    ):
        assert start_work_decision(
            state, deposit_cents=30_000, recorded_paid_cents=30_000
        ) == StartWorkDecision.ALREADY_STARTED


def test_start_work_blocks_unsigned_authorization() -> None:
    assert start_work_decision(
        WorkflowState.AUTHORIZATION_SENT, deposit_cents=30_000, recorded_paid_cents=0
    ) == StartWorkDecision.BLOCKED
