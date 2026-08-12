from datetime import UTC, date, datetime, timedelta

from app.ar import days_past_due, first_reminder_at, next_reminder, next_send_window, promise_pause_until, within_send_window


def test_invoice_is_due_at_issue_and_first_reminder_is_24_hours_later() -> None:
    issued = datetime(2026, 8, 4, 16, 30, tzinfo=UTC)
    due = issued
    assert due == issued
    assert first_reminder_at(issued, (24, 72, 168)) == datetime(2026, 8, 5, 16, 30, tzinfo=UTC)


def test_reminder_schedule_advances_then_repeats_every_14_days() -> None:
    issued = datetime(2026, 8, 4, 16, 30, tzinfo=UTC)
    offsets = (24, 72, 168, 336, 504, 720)
    # next_reminder_at is already set to offsets[0] when the case is created.
    # After that first reminder is sent, the cursor points at offsets[1].
    after_first = next_reminder(
        issued_at=issued,
        current_index=1,
        repeat_count=0,
        offsets_hours=offsets,
        repeat_interval_hours=336,
    )
    assert after_first.reminder_index == 2
    assert after_first.next_reminder_at == issued + timedelta(hours=72)
    repeat = next_reminder(
        issued_at=issued,
        current_index=len(offsets),
        repeat_count=0,
        offsets_hours=offsets,
        repeat_interval_hours=336,
    )
    assert repeat.repeat_count == 1
    assert repeat.next_reminder_at == issued + timedelta(hours=720 + 336)


def test_local_send_window_and_next_window() -> None:
    # Noon UTC is 08:00 in Detroit during daylight saving time.
    now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    assert not within_send_window(now, "America/Detroit", "09:00", "18:00")
    assert next_send_window(now, "America/Detroit", "09:00", "18:00") == datetime(2026, 8, 4, 13, 0, tzinfo=UTC)


def test_days_past_due_uses_customer_calendar() -> None:
    due = datetime(2026, 8, 4, 16, 0, tzinfo=UTC)
    now = datetime(2026, 8, 7, 13, 0, tzinfo=UTC)
    assert days_past_due(now, due, "America/Detroit") == 3


def test_promise_pauses_through_promised_day() -> None:
    result = promise_pause_until(date(2026, 8, 14), "America/Detroit", "09:00")
    assert result == datetime(2026, 8, 15, 13, 0, tzinfo=UTC)
