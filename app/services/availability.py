from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class BlockedInterval:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class AvailableSlot:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class BusinessHours:
    timezone: ZoneInfo
    open_time: time
    close_time: time
    working_weekdays: frozenset[int]  # 0=Monday .. 6=Sunday
    slot_step_minutes: int


def blocked_interval(
    start: datetime, duration_minutes: int, buffer_minutes: int
) -> BlockedInterval:
    """Build a blocked interval including mandatory post-session buffer."""
    return BlockedInterval(start, start + timedelta(minutes=duration_minutes + buffer_minutes))


def intervals_overlap(a: BlockedInterval, b: BlockedInterval) -> bool:
    """
    Two half-open intervals [a.start, a.end) and [b.start, b.end) overlap
    if max(a.start, b.start) < min(a.end, b.end).
    Touching at the exact boundary (a.end == b.start) is NOT an overlap.
    """
    return max(a.start, b.start) < min(a.end, b.end)


def compute_available_slots(
    *,
    date_from: date,
    date_to: date,
    duration_minutes: int,
    buffer_minutes: int,
    existing: list[BlockedInterval],
    hours: BusinessHours,
    now: datetime | None = None,
) -> list[AvailableSlot]:
    """
    Compute collision-free individual appointment slots across [date_from, date_to] (inclusive).
    Candidate slots are generated in the business timezone from open_time to close_time.
    A candidate slot is rejected if:
      1. Its actual session end (start + duration) exceeds close_time.
      2. Its start is at or before `now` (UTC).
      3. Its blocked interval (start + duration + buffer) overlaps with any existing blocked interval.
    """
    if date_to < date_from:
        raise ValueError("date_to cannot precede date_from")

    ref_now = now or datetime.now(UTC)
    slots: list[AvailableSlot] = []
    step = timedelta(minutes=hours.slot_step_minutes)
    session_delta = timedelta(minutes=duration_minutes)

    current_date = date_from
    while current_date <= date_to:
        if current_date.weekday() in hours.working_weekdays:
            day_open = datetime.combine(current_date, hours.open_time, tzinfo=hours.timezone)
            day_close = datetime.combine(current_date, hours.close_time, tzinfo=hours.timezone)

            candidate_start = day_open
            while candidate_start < day_close:
                session_end = candidate_start + session_delta
                if session_end > day_close:
                    break

                # Verify candidate is strictly in the future compared to ref_now
                candidate_start_utc = candidate_start.astimezone(UTC)
                if candidate_start_utc > ref_now:
                    candidate_blocked = blocked_interval(
                        candidate_start, duration_minutes, buffer_minutes
                    )
                    # Check collision against existing blocked intervals
                    has_collision = False
                    for b in existing:
                        # Normalize timezones for safety when comparing
                        b_start_norm = b.start.astimezone(hours.timezone)
                        b_end_norm = b.end.astimezone(hours.timezone)
                        if intervals_overlap(
                            candidate_blocked, BlockedInterval(b_start_norm, b_end_norm)
                        ):
                            has_collision = True
                            break

                    if not has_collision:
                        slots.append(AvailableSlot(start=candidate_start, end=session_end))

                candidate_start += step

        current_date += timedelta(days=1)

    return slots
