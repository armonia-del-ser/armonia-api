from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.availability import (
    BlockedInterval,
    BusinessHours,
    blocked_interval,
    compute_available_slots,
    intervals_overlap,
)

MX = ZoneInfo("America/Mexico_City")  # UTC-6, no DST since 2022
MONDAY = date(2027, 3, 1)
LONG_AGO = datetime(2020, 1, 1, tzinfo=UTC)

HOURS = BusinessHours(
    timezone=MX,
    open_time=time(9, 0),
    close_time=time(13, 0),
    working_weekdays=frozenset({0, 1, 2, 3, 4}),
    slot_step_minutes=30,
)


def _local(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=MX)


def _starts(slots) -> list[str]:
    return [s.start.strftime("%H:%M") for s in slots]


# --- blocked_interval / intervals_overlap -------------------------------------------


def test_blocked_interval_adds_duration_and_post_session_buffer():
    start = _local(MONDAY, 10)
    interval = blocked_interval(start, duration_minutes=60, buffer_minutes=15)
    assert interval.start == start
    assert interval.end == start + timedelta(minutes=75)


def test_intervals_touching_at_boundary_do_not_overlap():
    a = BlockedInterval(_local(MONDAY, 9), _local(MONDAY, 10))
    b = BlockedInterval(_local(MONDAY, 10), _local(MONDAY, 11))
    assert intervals_overlap(a, b) is False
    assert intervals_overlap(b, a) is False


def test_intervals_sharing_one_minute_overlap():
    a = BlockedInterval(_local(MONDAY, 9), _local(MONDAY, 10, 1))
    b = BlockedInterval(_local(MONDAY, 10), _local(MONDAY, 11))
    assert intervals_overlap(a, b) is True
    assert intervals_overlap(b, a) is True


def test_contained_interval_overlaps():
    outer = BlockedInterval(_local(MONDAY, 9), _local(MONDAY, 12))
    inner = BlockedInterval(_local(MONDAY, 10), _local(MONDAY, 11))
    assert intervals_overlap(outer, inner) is True
    assert intervals_overlap(inner, outer) is True


# --- compute_available_slots --------------------------------------------------------


def _compute(existing=(), *, duration=60, buffer=15, now=LONG_AGO, day_to=None, hours=HOURS):
    return compute_available_slots(
        date_from=MONDAY,
        date_to=day_to or MONDAY,
        duration_minutes=duration,
        buffer_minutes=buffer,
        existing=list(existing),
        hours=hours,
        now=now,
    )


def test_empty_day_offers_every_step_whose_session_ends_by_close():
    # 60-minute session must END by 13:00 -> last start 12:00
    assert _starts(_compute()) == ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00"]


def test_buffer_may_spill_past_closing_time():
    # 12:00 + 60 = 13:00 session end (allowed) even though buffer runs to 13:15
    assert "12:00" in _starts(_compute())


def test_slot_end_is_session_end_without_buffer():
    first = _compute()[0]
    assert first.end - first.start == timedelta(minutes=60)


def test_slots_are_returned_in_business_timezone():
    first = _compute()[0]
    assert first.start.utcoffset() == timedelta(hours=-6)
    assert first.start.astimezone(UTC).hour == 15


def test_existing_booking_blocks_its_buffer_and_new_sessions_buffer():
    # Existing 10:00 session blocks [10:00, 11:15)
    existing = [blocked_interval(_local(MONDAY, 10), 60, 15)]
    # 09:00 slot would block [09:00, 10:15) -> overlaps because of the NEW buffer
    # 11:00 slot starts before 11:15 -> overlaps because of the EXISTING buffer
    assert _starts(_compute(existing)) == ["11:30", "12:00"]


def test_slot_whose_buffer_ends_exactly_at_existing_start_is_available():
    # 15-min step so 08:45-style edges are representable; 09:45 + 60 + 15 = 11:00
    hours = BusinessHours(MX, time(9, 0), time(13, 0), frozenset({0}), 15)
    existing = [blocked_interval(_local(MONDAY, 11), 60, 15)]
    starts = _starts(_compute(existing, hours=hours))
    assert "09:45" in starts
    assert "10:00" not in starts  # 10:00 + 75 = 11:15 > 11:00


def test_slot_starting_exactly_at_existing_buffer_end_is_available():
    hours = BusinessHours(MX, time(9, 0), time(13, 0), frozenset({0}), 15)
    existing = [blocked_interval(_local(MONDAY, 9), 60, 15)]  # blocks until 10:15
    starts = _starts(_compute(existing, hours=hours))
    assert starts[0] == "10:15"
    assert "10:00" not in starts


def test_zero_buffer_service_still_respects_existing_buffer():
    existing = [blocked_interval(_local(MONDAY, 9), 60, 15)]  # blocks until 10:15
    starts = _starts(_compute(existing, buffer=0))
    assert "10:00" not in starts
    assert starts[0] == "10:30"


def test_bookings_on_other_days_do_not_block():
    existing = [blocked_interval(_local(MONDAY + timedelta(days=1), 10), 60, 15)]
    assert len(_compute(existing)) == 7


def test_past_and_current_slots_are_excluded():
    now = _local(MONDAY, 10).astimezone(UTC)
    starts = _starts(_compute(now=now))
    assert "10:00" not in starts
    assert starts[0] == "10:30"


def test_non_working_days_offer_no_slots():
    saturday, sunday = MONDAY + timedelta(days=5), MONDAY + timedelta(days=6)
    slots = compute_available_slots(
        date_from=saturday,
        date_to=sunday,
        duration_minutes=60,
        buffer_minutes=15,
        existing=[],
        hours=HOURS,
        now=LONG_AGO,
    )
    assert slots == []


def test_range_is_inclusive_of_both_endpoints():
    slots = _compute(day_to=MONDAY + timedelta(days=1))
    assert {s.start.date() for s in slots} == {MONDAY, MONDAY + timedelta(days=1)}


def test_session_longer_than_opening_hours_yields_nothing():
    assert _compute(duration=300) == []


def test_invalid_range_is_rejected():
    with pytest.raises(ValueError):
        compute_available_slots(
            date_from=MONDAY,
            date_to=MONDAY - timedelta(days=1),
            duration_minutes=60,
            buffer_minutes=15,
            existing=[],
            hours=HOURS,
            now=LONG_AGO,
        )
