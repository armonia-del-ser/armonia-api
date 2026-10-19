import uuid
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models.booking import (
    Booking,
    BookingPaymentStatusEnum,
    BookingStatusEnum,
    GcalSyncStatusEnum,
    PaymentArrangementEnum,
)


def test_booking_accepts_minimal_valid_payload():
    payload = {
        "booking_code": "ADS-1001",
        "service_id": "srv_abc",
        "client_id": "cli_xyz",
        "scheduled_at": "2026-10-25T10:00:00Z",
        "amount_mxn": 600,
    }
    booking = Booking.model_validate(payload)

    assert booking.booking_code == "ADS-1001"
    assert booking.service_id == "srv_abc"
    assert booking.client_id == "cli_xyz"
    assert booking.package_id is None
    assert booking.duration_minutes == 60
    assert booking.buffer_minutes == 0
    assert booking.booking_status is BookingStatusEnum.RESERVED
    assert booking.payment_arrangement is PaymentArrangementEnum.PREPAID_DEFAULT
    assert booking.payment_status is BookingPaymentStatusEnum.AWAITING_ACKNOWLEDGMENT
    assert booking.amount_mxn == 600
    assert booking.gcal_sync_status is GcalSyncStatusEnum.PENDING

    parsed_uuid = uuid.UUID(booking.id, version=4)
    assert str(parsed_uuid) == booking.id

    parsed_dt = datetime.fromisoformat(booking.created_at)
    assert parsed_dt.tzinfo is not None
    assert parsed_dt.utcoffset() == timedelta(0)


def test_booking_accepts_full_valid_payload():
    custom_id = str(uuid.uuid4())
    payload = {
        "id": custom_id,
        "booking_code": "ADS-2002",
        "service_id": "srv_abc",
        "client_id": "cli_xyz",
        "package_id": "pkg_123",
        "scheduled_at": "2026-10-26T15:00:00Z",
        "duration_minutes": 90,
        "buffer_minutes": 15,
        "booking_status": "COMPLETED",
        "payment_arrangement": "DELAYED_ALLOWED",
        "payment_status": "ACKNOWLEDGED",
        "amount_mxn": 800,
        "exception_authorized_by": "jasmin@armoniadelser.mx",
        "exception_authorized_at": "2026-10-24T12:00:00Z",
        "exception_notes": "Conocida de confianza",
        "acknowledged_by": "asistente@armoniadelser.mx",
        "acknowledged_at": "2026-10-26T16:30:00Z",
        "gcal_event_id": "gcal_evt_999",
        "gcal_sync_status": "SYNCED",
        "gcal_synced_at": "2026-10-24T12:01:00Z",
    }
    booking = Booking.model_validate(payload)

    assert booking.id == custom_id
    assert booking.booking_status is BookingStatusEnum.COMPLETED
    assert booking.payment_arrangement is PaymentArrangementEnum.DELAYED_ALLOWED
    assert booking.payment_status is BookingPaymentStatusEnum.ACKNOWLEDGED
    assert booking.exception_authorized_by == "jasmin@armoniadelser.mx"
    assert booking.gcal_sync_status is GcalSyncStatusEnum.SYNCED


def test_booking_rejects_negative_amount():
    with pytest.raises(ValidationError):
        Booking.model_validate(
            {
                "booking_code": "ADS-1002",
                "service_id": "srv_abc",
                "client_id": "cli_xyz",
                "scheduled_at": "2026-10-25T10:00:00Z",
                "amount_mxn": -50,
            }
        )


def test_booking_rejects_invalid_enums():
    with pytest.raises(ValidationError):
        Booking.model_validate(
            {
                "booking_code": "ADS-1003",
                "service_id": "srv_abc",
                "client_id": "cli_xyz",
                "scheduled_at": "2026-10-25T10:00:00Z",
                "amount_mxn": 500,
                "booking_status": "NON_EXISTENT_STATUS",
            }
        )
