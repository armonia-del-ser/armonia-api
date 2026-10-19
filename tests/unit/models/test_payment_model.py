import uuid
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models.payment import (
    Payment,
    PaymentMethodEnum,
    PaymentStatusEnum,
)


def test_payment_accepts_minimal_valid_payload():
    payload = {
        "booking_id": "bkg_123",
        "amount_mxn": 600,
        "acknowledged_by": "jasmin@armoniadelser.mx",
        "acknowledged_at": "2026-10-25T11:00:00Z",
    }
    payment = Payment.model_validate(payload)

    assert payment.booking_id == "bkg_123"
    assert payment.amount_mxn == 600
    assert payment.acknowledged_by == "jasmin@armoniadelser.mx"
    assert payment.acknowledged_at == "2026-10-25T11:00:00Z"
    assert payment.payment_method is PaymentMethodEnum.SPEI
    assert payment.payment_method == "SPEI"
    assert payment.status is PaymentStatusEnum.ACKNOWLEDGED
    assert payment.status == "ACKNOWLEDGED"
    assert payment.notes is None

    parsed_uuid = uuid.UUID(payment.id, version=4)
    assert str(parsed_uuid) == payment.id

    parsed_dt = datetime.fromisoformat(payment.created_at)
    assert parsed_dt.tzinfo is not None
    assert parsed_dt.utcoffset() == timedelta(0)


def test_payment_accepts_full_valid_payload():
    custom_id = str(uuid.uuid4())
    payload = {
        "id": custom_id,
        "booking_id": "bkg_456",
        "amount_mxn": 1200,
        "payment_method": "CASH",
        "status": "REVERSED",
        "acknowledged_by": "asistente@armoniadelser.mx",
        "acknowledged_at": "2026-10-25T12:00:00Z",
        "notes": "Reembolso acordado con el cliente",
    }
    payment = Payment.model_validate(payload)

    assert payment.id == custom_id
    assert payment.payment_method is PaymentMethodEnum.CASH
    assert payment.status is PaymentStatusEnum.REVERSED
    assert payment.notes == "Reembolso acordado con el cliente"


def test_payment_rejects_negative_amount():
    with pytest.raises(ValidationError):
        Payment.model_validate(
            {
                "booking_id": "bkg_123",
                "amount_mxn": -100,
                "acknowledged_by": "jasmin@armoniadelser.mx",
                "acknowledged_at": "2026-10-25T11:00:00Z",
            }
        )


def test_payment_rejects_invalid_enums():
    with pytest.raises(ValidationError):
        Payment.model_validate(
            {
                "booking_id": "bkg_123",
                "amount_mxn": 300,
                "payment_method": "BITCOIN",
                "acknowledged_by": "jasmin@armoniadelser.mx",
                "acknowledged_at": "2026-10-25T11:00:00Z",
            }
        )
