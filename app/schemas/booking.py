from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

BookingStatus = Literal["PENDING_PAYMENT", "CONFIRMED", "CANCELLED", "EXPIRED", "NO_SHOW"]


class BookingCreate(BaseModel):
    service_id: str
    client_name: str = Field(..., min_length=2)
    client_phone: str = Field(..., min_length=10)
    client_email: str | None = None
    scheduled_at: str = Field(..., description="ISO 8601 string for scheduled date and time")
    notes: str | None = None


class BookingRead(BaseModel):
    id: str
    booking_code: str
    service_id: str
    service_name: str | None = None
    client_id: str
    client_name: str | None = None
    client_phone: str | None = None
    scheduled_at: str
    status: BookingStatus
    amount_mxn: int
    gcal_event_id: str | None = None
    expires_at: str
    created_at: str
    confirmed_at: str | None = None
    whatsapp_redirect_url: str | None = None
