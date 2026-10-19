"""
Behavior-driven test naming convention:
test_<subject>_<action>_<expected>
"""

from datetime import UTC, datetime

import time_machine

from app.services.timestamps import utc_now_iso


def test_utc_now_iso_returns_exact_timestamp():
    # freeze time at a known UTC moment
    frozen_time: datetime = datetime(2026, 9, 26, 16, 0, 0, 500000, tzinfo=UTC)

    with time_machine.travel(frozen_time, tick=False):
        assert utc_now_iso() == "2026-09-26T16:00:00.500000+00:00"
