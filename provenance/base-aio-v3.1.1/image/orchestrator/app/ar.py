from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True, slots=True)
class ReminderAdvance:
    reminder_index: int
    repeat_count: int
    next_reminder_at: datetime


def parse_clock(value: str) -> time:
    hour, minute = (int(piece) for piece in value.split(":", 1))
    return time(hour=hour, minute=minute)


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("America/Detroit")


def next_reminder(
    *,
    issued_at: datetime,
    current_index: int,
    repeat_count: int,
    offsets_hours: tuple[int, ...],
    repeat_interval_hours: int,
) -> ReminderAdvance:
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=UTC)
    if current_index < len(offsets_hours):
        target = issued_at + timedelta(hours=offsets_hours[current_index])
        return ReminderAdvance(current_index + 1, repeat_count, target)
    base = issued_at + timedelta(hours=offsets_hours[-1])
    next_repeat = repeat_count + 1
    target = base + timedelta(hours=repeat_interval_hours * next_repeat)
    return ReminderAdvance(current_index, next_repeat, target)


def first_reminder_at(issued_at: datetime, offsets_hours: tuple[int, ...]) -> datetime:
    return issued_at + timedelta(hours=offsets_hours[0])


def is_past_due(now: datetime, due_at: datetime, balance_cents: int) -> bool:
    return balance_cents > 0 and now >= due_at


def days_past_due(now: datetime, due_at: datetime, timezone_name: str) -> int:
    tz = zone(timezone_name)
    local_now = now.astimezone(tz).date()
    local_due = due_at.astimezone(tz).date()
    return max(0, (local_now - local_due).days)


def within_send_window(now: datetime, timezone_name: str, start: str, end: str) -> bool:
    tz = zone(timezone_name)
    local = now.astimezone(tz)
    start_time = parse_clock(start)
    end_time = parse_clock(end)
    if start_time <= end_time:
        return start_time <= local.time().replace(tzinfo=None) < end_time
    return local.time().replace(tzinfo=None) >= start_time or local.time().replace(tzinfo=None) < end_time


def next_send_window(now: datetime, timezone_name: str, start: str, end: str) -> datetime:
    tz = zone(timezone_name)
    local = now.astimezone(tz)
    start_time = parse_clock(start)
    end_time = parse_clock(end)
    naive_time = local.time().replace(tzinfo=None)
    if start_time <= end_time and start_time <= naive_time < end_time:
        return now
    if start_time > end_time and (naive_time >= start_time or naive_time < end_time):
        return now
    local_date = local.date()
    if naive_time < start_time:
        target_date = local_date
    else:
        target_date = local_date + timedelta(days=1)
    target = datetime.combine(target_date, start_time, tzinfo=tz)
    return target.astimezone(UTC)


def promise_pause_until(promised_date: date, timezone_name: str, send_start: str) -> datetime:
    tz = zone(timezone_name)
    # Allow the promised calendar day to complete, then resume at the next normal send window.
    next_day = promised_date + timedelta(days=1)
    return datetime.combine(next_day, parse_clock(send_start), tzinfo=tz).astimezone(UTC)
