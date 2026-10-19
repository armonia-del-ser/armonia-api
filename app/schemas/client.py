from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.booking import BookingRead
from app.schemas.package import PackageRead

PHONE_WITH_EXT_REGEX = re.compile(
    r"^((?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?){2,4}\d{3,4})(?:[-.\s]*(?:ext|ext\.|x|#|extension)[-.\s]*(\d+))?$",
    re.IGNORECASE,
)


def validate_phone_format(v: str) -> str:
    clean_value = v.strip()
    if not PHONE_WITH_EXT_REGEX.match(clean_value):
        raise ValueError(
            "Invalid phone number format. Examples of valid formats: "
            "'+1 (555) 019-2834', '555-019-2834 ext 123', or '5550192834x12'"
        )
    return clean_value


class ClientBase(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=150)
    phone_whatsapp: str = Field(..., min_length=10, max_length=50)
    email: EmailStr | None = None
    notes: str | None = None

    @field_validator("phone_whatsapp")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return validate_phone_format(v)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.strip():
            return None
        return v


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    phone_whatsapp: str | None = Field(default=None, min_length=10, max_length=50)
    email: EmailStr | None = None
    notes: str | None = None

    @field_validator("phone_whatsapp")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return validate_phone_format(v)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.strip():
            return None
        return v


class ClientRead(ClientBase):
    id: str
    created_at: str


class Client360Read(BaseModel):
    id: str
    full_name: str
    phone_whatsapp: str
    email: EmailStr | None = None
    notes: str | None = None
    created_at: str
    active_packages: list[PackageRead] = Field(default_factory=list)
    booking_history: list[BookingRead] = Field(default_factory=list)
    recent_bookings: list[BookingRead] = Field(default_factory=list)


ClientDetailRead = Client360Read
