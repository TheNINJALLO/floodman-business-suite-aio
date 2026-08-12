from app.service import WorkflowService


class DummyReceivables:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, int | None]] = []

    def send_past_due_reminder(
        self,
        job_id: str,
        *,
        expected_case_id: str | None = None,
        expected_reminder_count: int | None = None,
    ) -> None:
        self.calls.append((job_id, expected_case_id, expected_reminder_count))


def test_outbox_reminder_carries_stale_event_guard() -> None:
    service = WorkflowService.__new__(WorkflowService)
    service.receivables = DummyReceivables()
    reconciled: list[tuple[str, dict[str, str]]] = []
    service.reconcile_job_payments = lambda job_id, payload: reconciled.append((job_id, payload))  # type: ignore[method-assign]

    service.send_ar_reminder("job-1", {"ar_case_id": "case-1", "reminder_count": 3})

    assert reconciled == [("job-1", {"reason": "pre_reminder_reconciliation"})]
    assert service.receivables.calls == [("job-1", "case-1", 3)]
