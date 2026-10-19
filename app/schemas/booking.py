from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

BookingStatus = Literal["RESERVED", "RELEASED", "CANCELLED", "COMPLETED", "NO_SHOW"]
PaymentArrangement = Literal["PREPAID_DEFAULT", "DELAYED_ALLOWED", "PACKAGE_REDEEMED"]
BookingPaymentStatus = Literal["AWAITING_ACKNOWLEDGMENT", "ACKNOWLEDGED", "NOT_APPLICABLE"]
CalendarSyncStatus = Literal["PENDING", "SYNCED", "FAILED", "NOT_CONFIGURED"]


class BookingCreate(BaseModel):
    service_id: str
    client_name: str = Field(..., min_length=2)
    client_phone: str = Field(..., min_length=10)
    client_email: str | None = None
    scheduled_at: str = Field(..., description="ISO 8601 string for scheduled date and time")
    notes: str | None = None
    package_id: str | None = None


class DelayedPaymentAuthorizeRequest(BaseModel):
    notes: str | None = Field(
        default=None,
        description="Optional administrative explanation for allowing delayed payment",
    )


class BookingReleaseRequest(BaseModel):
    reason: str | None = Field(
        default=None,
        description="Optional administrative reason for releasing the slot",
    )


class BookingStatusUpdateRequest(BaseModel):
    booking_status: Literal["COMPLETED", "CANCELLED", "NO_SHOW"]
    notes: str | None = None


class BookingRead(BaseModel):
    id: str
    booking_code: str
    service_id: str
    service_name: str | None = None
    client_id: str
    client_name: str | None = None
    client_phone: str | None = None
    package_id: str | None = None
    scheduled_at: str
    duration_minutes: int = 60
    buffer_minutes: int = 0
    booking_status: BookingStatus
    payment_arrangement: PaymentArrangement
    payment_status: BookingPaymentStatus
    amount_mxn: int
    needs_payment_followup: bool = False
    hours_until_session: float = 0.0
    exception_authorized_by: str | None = None
    exception_authorized_at: str | None = None
    exception_notes: str | None = None
    released_by: str | None = None
    released_at: str | None = None
    release_reason: str | None = None
    acknowledged_by: str | None = None
    acknowledged_at: str | None = None
    gcal_event_id: str | None = None
    gcal_sync_status: CalendarSyncStatus = "NOT_CONFIGURED"
    gcal_sync_error: str | None = None
    gcal_synced_at: str | None = None
    created_at: str
    whatsapp_redirect_url: str | None = None
    whatsapp_followup_url: str | None = None
