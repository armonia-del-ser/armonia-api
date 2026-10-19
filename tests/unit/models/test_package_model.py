import uuid
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models.package import FinancialStatusEnum, Package


def test_package_accepts_minimal_valid_payload():
    payload = {
        "client_id": "cli_123",
        "service_id": "srv_456",
        "total_sessions": 5,
    }
    package = Package.model_validate(payload)

    assert package.client_id == "cli_123"
    assert package.service_id == "srv_456"
    assert package.total_sessions == 5
    assert package.completed_sessions == 0
    assert package.price_paid_mxn == 0
    assert package.financial_status is FinancialStatusEnum.PENDING
    assert package.financial_status == "PENDING"
    assert package.notes is None

    # Auto-generated UUID4
    parsed_uuid = uuid.UUID(package.id, version=4)
    assert str(parsed_uuid) == package.id

    # Timestamps
    created_dt = datetime.fromisoformat(package.created_at)
    assert created_dt.tzinfo is not None
    assert created_dt.utcoffset() == timedelta(0)


def test_package_accepts_full_valid_payload():
    custom_id = str(uuid.uuid4())
    payload = {
        "id": custom_id,
        "client_id": "cli_123",
        "service_id": "srv_456",
        "total_sessions": 10,
        "completed_sessions": 3,
        "price_paid_mxn": 2500,
        "financial_status": "PAID",
        "notes": "Pagado en efectivo por adelantado",
    }
    package = Package.model_validate(payload)

    assert package.id == custom_id
    assert package.completed_sessions == 3
    assert package.price_paid_mxn == 2500
    assert package.financial_status is FinancialStatusEnum.PAID
    assert package.notes == "Pagado en efectivo por adelantado"


def test_package_rejects_zero_or_negative_total_sessions():
    with pytest.raises(ValidationError):
        Package.model_validate(
            {
                "client_id": "cli_123",
                "service_id": "srv_456",
                "total_sessions": 0,
            }
        )

    with pytest.raises(ValidationError):
        Package.model_validate(
            {
                "client_id": "cli_123",
                "service_id": "srv_456",
                "total_sessions": -2,
            }
        )


def test_package_rejects_invalid_financial_status():
    with pytest.raises(ValidationError):
        Package.model_validate(
            {
                "client_id": "cli_123",
                "service_id": "srv_456",
                "total_sessions": 5,
                "financial_status": "UNKNOWN_STATUS",
            }
        )
