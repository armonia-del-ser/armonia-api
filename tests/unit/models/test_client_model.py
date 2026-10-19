"""
Behavior-driven test naming convention:
test_<subject>_<accepts|rejects>_<condition>
"""

import uuid
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models import Client


def test_client_accepts_minimal_valid_payload():
    payload = {
        "full_name": "Luisa Santos",
        "phone_whatsapp": "+1 (555) 019-2834",
    }
    client = Client.model_validate(payload)

    assert client.full_name == "Luisa Santos"
    assert client.phone_whatsapp == "+1 (555) 019-2834"
    assert client.email is None
    assert client.notes is None

    # Check UUID4 string format
    assert isinstance(client.id, str)
    parsed_uuid = uuid.UUID(client.id, version=4)
    assert str(parsed_uuid) == client.id

    # Check created_at parsing and UTC offset
    parsed_dt = datetime.fromisoformat(client.created_at)
    assert isinstance(parsed_dt, datetime)
    assert parsed_dt.tzinfo is not None
    assert parsed_dt.utcoffset() == timedelta(0)


def test_client_accepts_full_valid_payload():
    custom_id = str(uuid.uuid4())
    payload = {
        "id": custom_id,
        "full_name": "Valentina Vega",
        "phone_whatsapp": "555-019-2834 ext 123",
        "email": "testing_vvt@roadtotech.me",
        "notes": "Prefers morning appointments.",
    }

    client = Client.model_validate(payload)

    assert client.id == custom_id
    assert client.full_name == "Valentina Vega"
    assert client.phone_whatsapp == "555-019-2834 ext 123"
    assert client.email == "testing_vvt@roadtotech.me"
    assert client.notes == "Prefers morning appointments."


@pytest.mark.parametrize(
    "valid_phone",
    [
        "+13005386982",
        "+1 (555) 019-2834",
        "555-019-2834 ext 123",
        "5550192834x12",
        "(555) 019-2834 #456",
        "+57 300 123 4567",
    ],
)
def test_client_accepts_valid_phone_formats(valid_phone: str):
    payload = {"full_name": "Anthonio Stark", "phone_whatsapp": valid_phone}

    client = Client.model_validate(payload)

    assert client.phone_whatsapp == valid_phone.strip()


def test_client_rejects_missing_required_fields():
    # Missing full_name and phone_whatsapp
    with pytest.raises(ValidationError) as exc_info:
        Client.model_validate({})

    errors = exc_info.value.errors()
    missing_locs = {err["loc"][0] for err in errors}
    assert "full_name" in missing_locs
    assert "phone_whatsapp" in missing_locs


@pytest.mark.parametrize(
    "invalid_phone",
    [
        "",
        "not-a-number",
        "123",
        "++15550192834",
        "555-PHONE-NOW",
    ],
)
def test_client_rejects_invalid_phone_formats(invalid_phone: str):
    payload = {
        "full_name": "Luisa Santos",
        "phone_whatsapp": invalid_phone,
    }
    with pytest.raises(ValidationError) as exc_info:
        Client.model_validate(payload)

    errors = exc_info.value.errors()
    assert any(err["loc"][0] == "phone_whatsapp" for err in errors)


@pytest.mark.parametrize(
    "invalid_email",
    [
        "plainaddress",
        "@missingusername.com",
        "user@.com",
        "user@domain..com",
    ],
)
def test_client_rejects_invalid_email(invalid_email: str):
    payload = {
        "full_name": "Luisa Santos",
        "phone_whatsapp": "+13005386982",
        "email": invalid_email,
    }
    with pytest.raises(ValidationError) as exc_info:
        Client.model_validate(payload)

    errors = exc_info.value.errors()
    assert any(err["loc"][0] == "email" for err in errors)


def test_client_rejects_non_string_types_in_strict_mode():
    # strict=True prevents coercion of integers/booleans to strings
    payload = {
        "full_name": 12345,
        "phone_whatsapp": "+13005386982",
    }
    with pytest.raises(ValidationError) as exc_info:
        Client.model_validate(payload)

    errors = exc_info.value.errors()
    assert any(err["loc"][0] == "full_name" for err in errors)
