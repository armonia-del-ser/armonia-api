"""
Behavior-driven test naming convention:
test_<subject>_<accepts|rejects>_<condition>
"""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models.service import (
    Service,
    ServiceModalityEnum,
    ServiceTypeEnum,
)


def test_service_accepts_minimal_valid_payload():
    payload = {
        "slug": "tarot-reading",
        "name": "Tarot Reading",
        "service_type": "INDIVIDUAL",
        "modality": "ONLINE",
    }
    service = Service.model_validate(payload)

    assert service.slug == "tarot-reading"
    assert service.name == "Tarot Reading"
    assert service.service_type is ServiceTypeEnum.INDIVIDUAL
    assert service.modality is ServiceModalityEnum.ONLINE
    assert service.service_type == "INDIVIDUAL"
    assert service.modality == "ONLINE"

    # Default values verification
    assert service.id is None
    assert service.description is None
    assert service.default_schedule is None
    assert service.price_mxn == 0
    assert service.max_capacity == 1
    assert service.duration_minutes == 60
    assert service.buffer_minutes == 15
    assert service.is_active is True

    # Valid UTC ISO timestamp verification
    parsed_dt = datetime.fromisoformat(service.created_at)
    assert isinstance(parsed_dt, datetime)
    assert parsed_dt.tzinfo is not None
    assert parsed_dt.utcoffset() == timedelta(0)


def test_service_accepts_full_valid_payload():
    payload = {
        "id": "srv_123456",
        "slug": "reiki-in-person",
        "name": "Reiki Session",
        "description": "60-minute energy balance session.",
        "service_type": "INDIVIDUAL",
        "modality": "PRESENCIAL",
        "default_schedule": "mon-fri_09-17",
        "price_mxn": 850,
        "max_capacity": 2,
        "duration_minutes": 90,
        "buffer_minutes": 20,
        "is_active": False,
    }
    service = Service.model_validate(payload)

    assert service.id == "srv_123456"
    assert service.service_type is ServiceTypeEnum.INDIVIDUAL
    assert service.modality is ServiceModalityEnum.PRESENCIAL
    assert service.price_mxn == 850
    assert service.max_capacity == 2
    assert service.duration_minutes == 90
    assert service.buffer_minutes == 20
    assert service.is_active is False


@pytest.mark.parametrize("valid_type", ["GROUP", "INDIVIDUAL"])
def test_service_accepts_all_valid_service_types(valid_type: str):
    payload = {
        "slug": f"service-{valid_type.lower()}",
        "name": "Sample Service",
        "service_type": valid_type,
        "modality": "ONLINE",
    }
    service = Service.model_validate(payload)
    assert service.service_type == ServiceTypeEnum(valid_type)
    assert service.service_type == valid_type


@pytest.mark.parametrize("valid_modality", ["PRESENCIAL", "ONLINE"])
def test_service_accepts_all_valid_modalities(valid_modality: str):
    payload = {
        "slug": f"service-{valid_modality.lower()}",
        "name": "Sample Service",
        "service_type": "GROUP",
        "modality": valid_modality,
    }
    service = Service.model_validate(payload)
    assert service.modality == ServiceModalityEnum(valid_modality)
    assert service.modality == valid_modality


def test_service_accepts_enum_instances_directly():
    payload = {
        "slug": "meditation-class",
        "name": "Meditation Class",
        "service_type": ServiceTypeEnum.GROUP,
        "modality": ServiceModalityEnum.PRESENCIAL,
    }
    service = Service.model_validate(payload)
    assert service.service_type is ServiceTypeEnum.GROUP
    assert service.modality is ServiceModalityEnum.PRESENCIAL


def test_service_rejects_missing_required_fields():
    with pytest.raises(ValidationError) as exc_info:
        Service.model_validate({})

    errors = exc_info.value.errors()
    missing_locs = {err["loc"][0] for err in errors}
    assert {"slug", "name", "service_type", "modality"}.issubset(missing_locs)


@pytest.mark.parametrize(
    "invalid_type",
    [
        "group",  # Lowercase rejected
        "individual",  # Lowercase rejected
        "one_on_one",  # Legacy format rejected
        "Group",  # Mixed case rejected
        "consultation",
        "workshop",
        "",
        123,
    ],
)
def test_service_rejects_invalid_service_type(invalid_type):
    payload = {
        "slug": "sample-service",
        "name": "Sample Service",
        "service_type": invalid_type,
        "modality": "ONLINE",
    }
    with pytest.raises(ValidationError) as exc_info:
        Service.model_validate(payload)

    errors = exc_info.value.errors()
    assert any(err["loc"][0] == "service_type" for err in errors)


@pytest.mark.parametrize(
    "invalid_modality",
    [
        "presencial",  # Lowercase rejected
        "online",  # Lowercase rejected
        "Online",  # Mixed case rejected
        "hybrid",
        "remote",
        "",
        456,
    ],
)
def test_service_rejects_invalid_modality(invalid_modality):
    payload = {
        "slug": "sample-service",
        "name": "Sample Service",
        "service_type": "GROUP",
        "modality": invalid_modality,
    }
    with pytest.raises(ValidationError) as exc_info:
        Service.model_validate(payload)

    errors = exc_info.value.errors()
    assert any(err["loc"][0] == "modality" for err in errors)


@pytest.mark.parametrize(
    "field,invalid_value",
    [
        ("price_mxn", -1),  # ge=0
        ("max_capacity", 0),  # ge=1
        ("duration_minutes", 14),  # ge=15
        ("duration_minutes", -5),  # ge=15
        ("buffer_minutes", -1),  # ge=0
    ],
)
def test_service_rejects_out_of_bounds_numerical_values(field: str, invalid_value: int):
    payload = {
        "slug": "sound-bath",
        "name": "Sound Bath",
        "service_type": "GROUP",
        "modality": "PRESENCIAL",
        field: invalid_value,
    }
    with pytest.raises(ValidationError) as exc_info:
        Service.model_validate(payload)

    errors = exc_info.value.errors()
    assert any(err["loc"][0] == field for err in errors)


def test_service_rejects_non_integer_numbers_in_strict_mode():
    payload = {
        "slug": "yoga-class",
        "name": "Yoga Class",
        "service_type": "GROUP",
        "modality": "ONLINE",
        "price_mxn": "100",  # String instead of int in strict mode
    }
    with pytest.raises(ValidationError) as exc_info:
        Service.model_validate(payload)

    errors = exc_info.value.errors()
    assert any(err["loc"][0] == "price_mxn" for err in errors)
