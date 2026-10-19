"""
Behavior-driven test naming convention:
test_<subject>_<action>_<expected>
"""

from datetime import UTC, datetime

import time_machine

from app.services.timestamps import parse_iso_datetime, utc_now_iso


def test_utc_now_iso_returns_exact_timestamp():
    # freeze time at a known UTC moment
    frozen_time: datetime = datetime(2026, 9, 26, 16, 0, 0, 500000, tzinfo=UTC)

    with time_machine.travel(frozen_time, tick=False):
        assert utc_now_iso() == "2026-09-26T16:00:00.500000+00:00"


def test_parse_iso_datetime_naive_string_normalizes_to_utc():
    parsed = parse_iso_datetime("2026-10-27T10:00:00")
    assert parsed.tzinfo == UTC
    assert parsed.year == 2026
    assert parsed.month == 10
    assert parsed.day == 27
    assert parsed.hour == 10
    assert parsed.minute == 0


def test_parse_iso_datetime_aware_string_retains_utc():
    parsed = parse_iso_datetime("2026-10-27T10:00:00+00:00")
    assert parsed.tzinfo is not None
    assert parsed.tzinfo == UTC
    assert parsed.hour == 10
