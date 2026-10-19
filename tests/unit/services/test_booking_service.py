from __future__ import annotations

from datetime import UTC, datetime, timedelta

import time_machine

from app.core.config import settings
from app.services.bookings import (
    build_assistant_followup_link,
    build_whatsapp_link,
    calculate_hours_until,
    check_slot_collision,
    evaluate_payment_followup,
    generate_booking_code,
)

# ==============================================================================
# Buffer Collision Arithmetic (check_slot_collision)
# ==============================================================================


def test_collision_when_slots_overlap_in_middle():
    # Existing booking: 10:00 - 11:00 (+15m buffer = 11:15)
    existing = [
        {"scheduled_at": "2026-10-27T10:00:00Z", "duration_minutes": 60, "buffer_minutes": 15}
    ]
    # New slot starts inside existing slot: 10:30 - 11:30
    new_start = datetime(2026, 10, 27, 10, 30, tzinfo=UTC)
    assert check_slot_collision(new_start, 60, 15, existing) is True


def test_collision_when_exact_same_start_and_duration():
    existing = [
        {"scheduled_at": "2026-10-27T10:00:00Z", "duration_minutes": 60, "buffer_minutes": 15}
    ]
    new_start = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)
    assert check_slot_collision(new_start, 60, 15, existing) is True


def test_collision_when_new_slot_starts_during_existing_buffer():
    # Existing booking: 10:00 - 11:00 (+ 15m buffer = blocked until 11:15)
    existing = [
        {"scheduled_at": "2026-10-27T10:00:00Z", "duration_minutes": 60, "buffer_minutes": 15}
    ]
    # New slot: 11:05 - 12:05 (starts within existing buffer)
    new_start = datetime(2026, 10, 27, 11, 5, tzinfo=UTC)
    assert check_slot_collision(new_start, 60, 15, existing) is True


def test_no_collision_when_new_slot_starts_exactly_at_buffer_end_boundary():
    # Existing booking: 10:00 - 11:00 (+ 15m buffer = blocked until 11:15)
    existing = [
        {"scheduled_at": "2026-10-27T10:00:00Z", "duration_minutes": 60, "buffer_minutes": 15}
    ]
    # New slot: 11:15 - 12:15 (exact boundary: new_start == exist_blocked_end)
    new_start = datetime(2026, 10, 27, 11, 15, tzinfo=UTC)
    assert check_slot_collision(new_start, 60, 15, existing) is False


def test_no_collision_when_new_slot_blocked_end_exactly_matches_existing_start():
    # Existing booking: 11:15 - 12:15 (+ 15m buffer)
    existing = [
        {"scheduled_at": "2026-10-27T11:15:00Z", "duration_minutes": 60, "buffer_minutes": 15}
    ]
    # New slot: 10:00 - 11:00 (+ 15m buffer = blocked until 11:15)
    # Exact boundary: new_blocked_end == exist_start
    new_start = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)
    assert check_slot_collision(new_start, 60, 15, existing) is False


def test_collision_when_new_slot_buffer_encroaches_on_existing_start():
    # Existing booking: 11:10 - 12:10 (+ 15m buffer)
    existing = [
        {"scheduled_at": "2026-10-27T11:10:00Z", "duration_minutes": 60, "buffer_minutes": 15}
    ]
    # New slot: 10:00 - 11:00 (+ 15m buffer = blocked until 11:15 > 11:10)
    # The session itself ended at 11:00, but its mandatory buffer collides with 11:10!
    new_start = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)
    assert check_slot_collision(new_start, 60, 15, existing) is True


def test_no_collision_when_completely_disjoint_after():
    existing = [
        {"scheduled_at": "2026-10-27T10:00:00Z", "duration_minutes": 60, "buffer_minutes": 15}
    ]
    new_start = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
    assert check_slot_collision(new_start, 60, 15, existing) is False


def test_no_collision_when_completely_disjoint_before():
    existing = [
        {"scheduled_at": "2026-10-27T14:00:00Z", "duration_minutes": 60, "buffer_minutes": 15}
    ]
    new_start = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)
    assert check_slot_collision(new_start, 60, 15, existing) is False


def test_collision_defaults_for_missing_duration_and_buffer_keys():
    # Missing duration_minutes defaults to 60, missing buffer_minutes defaults to 0
    existing = [{"scheduled_at": "2026-10-27T10:00:00Z"}]
    # New slot at 10:45 collides with default 60-min slot (10:00-11:00)
    new_start = datetime(2026, 10, 27, 10, 45, tzinfo=UTC)
    assert check_slot_collision(new_start, 30, 0, existing) is True

    # New slot at 11:00 does not collide because default buffer is 0
    new_start_boundary = datetime(2026, 10, 27, 11, 0, tzinfo=UTC)
    assert check_slot_collision(new_start_boundary, 30, 0, existing) is False


def test_collision_with_multiple_existing_bookings_second_matches():
    existing = [
        {"scheduled_at": "2026-10-27T08:00:00Z", "duration_minutes": 60, "buffer_minutes": 15},
        {"scheduled_at": "2026-10-27T14:00:00Z", "duration_minutes": 90, "buffer_minutes": 15},
    ]
    # Collides with the 14:00-15:45 slot
    new_start = datetime(2026, 10, 27, 14, 30, tzinfo=UTC)
    assert check_slot_collision(new_start, 60, 15, existing) is True


# ==============================================================================
# Hours Until Calculation (calculate_hours_until)
# ==============================================================================


def test_calculate_hours_until_exact_hours_and_fractional():
    ref = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    target = datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC)
    assert calculate_hours_until(target, now=ref) == 48.0

    target_half = datetime(2026, 10, 27, 12, 30, 0, tzinfo=UTC)
    assert calculate_hours_until(target_half, now=ref) == 48.5


def test_calculate_hours_until_past_session_returns_negative():
    ref = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    past = datetime(2026, 10, 25, 10, 0, 0, tzinfo=UTC)
    assert calculate_hours_until(past, now=ref) == -2.0


def test_calculate_hours_until_from_iso_string():
    ref = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    assert calculate_hours_until("2026-10-27T12:00:00Z", now=ref) == 48.0


def test_calculate_hours_until_from_naive_datetime():
    ref = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    naive_target = datetime(2026, 10, 27, 12, 0, 0)
    assert calculate_hours_until(naive_target, now=ref) == 48.0


def test_calculate_hours_until_uses_datetime_now_when_now_is_none():
    frozen_ref = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    with time_machine.travel(frozen_ref, tick=False):
        target = "2026-10-27T12:00:00Z"
        assert calculate_hours_until(target) == 48.0


def test_calculate_hours_until_rounding_to_two_decimals():
    ref = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    # 1 hour and 20 seconds = 3620s -> 3620 / 3600 = 1.00555... -> 1.01
    target = ref + timedelta(seconds=3620)
    assert calculate_hours_until(target, now=ref) == 1.01


# ==============================================================================
# Payment Follow-Up Evaluation (evaluate_payment_followup)
# ==============================================================================


def test_payment_followup_false_when_payment_not_awaiting_acknowledgment():
    assert (
        evaluate_payment_followup(
            booking_status="RESERVED",
            payment_status="ACKNOWLEDGED",
            payment_arrangement="PREPAID_DEFAULT",
            hours_until=10.0,
            threshold_hours=48,
        )
        is False
    )
    assert (
        evaluate_payment_followup(
            booking_status="RESERVED",
            payment_status="NOT_APPLICABLE",
            payment_arrangement="PACKAGE_REDEEMED",
            hours_until=10.0,
            threshold_hours=48,
        )
        is False
    )


def test_payment_followup_at_exact_48h_boundary_is_true():
    # Exactly at threshold 48.0 hours -> must trigger follow-up
    assert (
        evaluate_payment_followup(
            booking_status="RESERVED",
            payment_status="AWAITING_ACKNOWLEDGMENT",
            payment_arrangement="PREPAID_DEFAULT",
            hours_until=48.0,
            threshold_hours=48,
        )
        is True
    )


def test_payment_followup_uses_48h_as_default_threshold():
    # Verify default parameter threshold_hours=48
    assert (
        evaluate_payment_followup(
            booking_status="RESERVED",
            payment_status="AWAITING_ACKNOWLEDGMENT",
            payment_arrangement="PREPAID_DEFAULT",
            hours_until=48.0,
        )
        is True
    )
    # At 48.01 or 49.0 hours, with default threshold=48, it must return False
    assert (
        evaluate_payment_followup(
            booking_status="RESERVED",
            payment_status="AWAITING_ACKNOWLEDGMENT",
            payment_arrangement="PREPAID_DEFAULT",
            hours_until=48.01,
        )
        is False
    )
    assert (
        evaluate_payment_followup(
            booking_status="RESERVED",
            payment_status="AWAITING_ACKNOWLEDGMENT",
            payment_arrangement="PREPAID_DEFAULT",
            hours_until=49.0,
        )
        is False
    )


def test_payment_followup_custom_threshold_window():
    assert (
        evaluate_payment_followup(
            booking_status="RESERVED",
            payment_status="AWAITING_ACKNOWLEDGMENT",
            payment_arrangement="PREPAID_DEFAULT",
            hours_until=72.0,
            threshold_hours=72,
        )
        is True
    )
    assert (
        evaluate_payment_followup(
            booking_status="RESERVED",
            payment_status="AWAITING_ACKNOWLEDGMENT",
            payment_arrangement="PREPAID_DEFAULT",
            hours_until=72.01,
            threshold_hours=72,
        )
        is False
    )


def test_payment_followup_delayed_allowed_for_reserved_and_completed_beyond_threshold():
    # DELAYED_ALLOWED triggers even when session is far in future
    assert (
        evaluate_payment_followup(
            booking_status="RESERVED",
            payment_status="AWAITING_ACKNOWLEDGMENT",
            payment_arrangement="DELAYED_ALLOWED",
            hours_until=120.0,
        )
        is True
    )
    # DELAYED_ALLOWED triggers for COMPLETED sessions (post-session payment)
    assert (
        evaluate_payment_followup(
            booking_status="COMPLETED",
            payment_status="AWAITING_ACKNOWLEDGMENT",
            payment_arrangement="DELAYED_ALLOWED",
            hours_until=-5.0,
        )
        is True
    )
    # Does NOT trigger for RELEASED or CANCELLED
    assert (
        evaluate_payment_followup(
            booking_status="RELEASED",
            payment_status="AWAITING_ACKNOWLEDGMENT",
            payment_arrangement="DELAYED_ALLOWED",
            hours_until=-5.0,
        )
        is False
    )
    assert (
        evaluate_payment_followup(
            booking_status="CANCELLED",
            payment_status="AWAITING_ACKNOWLEDGMENT",
            payment_arrangement="DELAYED_ALLOWED",
            hours_until=10.0,
        )
        is False
    )


# ==============================================================================
# Folio Code & WhatsApp Generation
# ==============================================================================


def test_generate_booking_code_format():
    code = generate_booking_code()
    assert code.startswith("ADS-")
    assert len(code) == 8
    suffix = code[4:]
    assert suffix == suffix.upper()
    assert all(c in "0123456789ABCDEF" for c in suffix)


def test_build_whatsapp_link_standalone_and_package():
    # Standalone booking link includes SPEI details
    link = build_whatsapp_link(
        service_name="Terapia Holística",
        scheduled_at="2026-10-27T10:00:00Z",
        folio="ADS-1A2B",
        amount_mxn=700,
    )
    assert "https://wa.me/" in link
    assert "ADS-1A2B" in link
    assert "700" in link
    assert settings.spei_bank in link

    # Package booking excludes bank details
    pkg_link = build_whatsapp_link(
        service_name="Terapia Holística",
        scheduled_at="2026-10-27T10:00:00Z",
        folio="ADS-1A2B",
        amount_mxn=700,
        package_info="Sesión 2/5",
    )
    assert "https://wa.me/" in pkg_link
    assert "Sesi%C3%B3n%202/5" in pkg_link or "Sesión 2/5" in pkg_link
    assert "CLABE" not in pkg_link


def test_build_assistant_followup_link_phone_normalization():
    # 10-digit number gets Mexican 52 prefix
    link_10 = build_assistant_followup_link(
        client_name="María Pérez",
        client_phone="5512345678",
        service_name="Cacao",
        scheduled_at="2026-10-27",
        folio="ADS-9999",
        amount_mxn=350,
    )
    assert "https://wa.me/525512345678" in link_10
    assert "Mar%C3%ADa%20P%C3%A9rez" in link_10 or "María Pérez" in link_10

    # Formatted with +, -, spaces
    link_formatted = build_assistant_followup_link(
        client_name="María",
        client_phone="+52 55-1234-5678",
        service_name="Cacao",
        scheduled_at="2026-10-27",
        folio="ADS-9999",
        amount_mxn=350,
    )
    assert "https://wa.me/525512345678" in link_formatted
