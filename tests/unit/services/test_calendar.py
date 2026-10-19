from __future__ import annotations

import pytest

from app.services.calendar import (
    CalendarService,
    compute_calendar_prefix,
)


@pytest.mark.parametrize(
    ("booking_status", "payment_arrangement", "payment_status", "expected_prefix"),
    [
        ("RELEASED", "PREPAID_DEFAULT", "AWAITING_ACKNOWLEDGMENT", "[LIBERADO]"),
        ("CANCELLED", "PREPAID_DEFAULT", "ACKNOWLEDGED", "[LIBERADO]"),
        ("RESERVED", "PREPAID_DEFAULT", "ACKNOWLEDGED", "[CONFIRMADO]"),
        ("RESERVED", "PACKAGE_REDEEMED", "NOT_APPLICABLE", "[CONFIRMADO]"),
        ("RESERVED", "DELAYED_ALLOWED", "AWAITING_ACKNOWLEDGMENT", "[PAGO DIFERIDO]"),
        ("RESERVED", "PREPAID_DEFAULT", "AWAITING_ACKNOWLEDGMENT", "[PAGO PENDIENTE]"),
    ],
)
def test_compute_calendar_prefix_states(
    booking_status: str,
    payment_arrangement: str,
    payment_status: str,
    expected_prefix: str,
):
    assert (
        compute_calendar_prefix(
            booking_status=booking_status,
            payment_arrangement=payment_arrangement,
            payment_status=payment_status,
        )
        == expected_prefix
    )


@pytest.mark.asyncio
async def test_calendar_service_not_configured_when_no_credentials(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "google_service_account_json", None)
    service = CalendarService()
    result = await service.sync_booking_event(
        booking_id="b-1",
        booking_code="ADS-1234",
        service_name="Terapia",
        client_name="Juan",
        scheduled_at="2026-10-27T10:00:00Z",
        duration_minutes=60,
        booking_status="RESERVED",
        payment_arrangement="PREPAID_DEFAULT",
        payment_status="AWAITING_ACKNOWLEDGMENT",
        existing_event_id="evt-old",
    )
    assert result.sync_status == "NOT_CONFIGURED"
    assert result.event_id == "evt-old"
    assert result.sync_error is None


@pytest.mark.asyncio
async def test_calendar_service_mock_gcal_sync_success(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "google_service_account_json", "mock-gcal")
    service = CalendarService()

    # New event generation
    res = await service.sync_booking_event(
        booking_id="12345678-abcd-1111-2222-333333333333",
        booking_code="ADS-1234",
        service_name="Cacao",
        client_name="Lucia",
        scheduled_at="2026-10-27T10:00:00",
        duration_minutes=60,
        booking_status="RESERVED",
        payment_arrangement="PREPAID_DEFAULT",
        payment_status="ACKNOWLEDGED",
    )
    assert res.sync_status == "SYNCED"
    assert res.event_id == "gcal-12345678"
    assert res.sync_error is None
    assert res.synced_at is not None

    # Preserves existing event_id
    res_existing = await service.sync_booking_event(
        booking_id="12345678-abcd-1111-2222-333333333333",
        booking_code="ADS-1234",
        service_name="Cacao",
        client_name="Lucia",
        scheduled_at="2026-10-27T10:00:00Z",
        duration_minutes=60,
        booking_status="RESERVED",
        payment_arrangement="PREPAID_DEFAULT",
        payment_status="ACKNOWLEDGED",
        existing_event_id="gcal-existing-99",
    )
    assert res_existing.event_id == "gcal-existing-99"

    # Released/Cancelled booking clears event_id
    res_released = await service.sync_booking_event(
        booking_id="12345678-abcd-1111-2222-333333333333",
        booking_code="ADS-1234",
        service_name="Cacao",
        client_name="Lucia",
        scheduled_at="2026-10-27T10:00:00Z",
        duration_minutes=60,
        booking_status="RELEASED",
        payment_arrangement="PREPAID_DEFAULT",
        payment_status="AWAITING_ACKNOWLEDGMENT",
        existing_event_id="gcal-existing-99",
    )
    assert res_released.event_id is None
    assert res_released.sync_status == "SYNCED"


@pytest.mark.asyncio
async def test_calendar_service_fail_gcal_captures_error(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "google_service_account_json", "fail-gcal")
    service = CalendarService()
    res = await service.sync_booking_event(
        booking_id="12345678-abcd-1111-2222-333333333333",
        booking_code="ADS-1234",
        service_name="Cacao",
        client_name="Lucia",
        scheduled_at="2026-10-27T10:00:00Z",
        duration_minutes=60,
        booking_status="RESERVED",
        payment_arrangement="PREPAID_DEFAULT",
        payment_status="AWAITING_ACKNOWLEDGMENT",
        existing_event_id="gcal-keep-id",
    )
    assert res.sync_status == "FAILED"
    assert res.event_id == "gcal-keep-id"
    assert "503" in (res.sync_error or "")
    assert res.synced_at is not None
