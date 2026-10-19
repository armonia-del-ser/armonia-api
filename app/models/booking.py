import uuid
from enum import StrEnum
from typing import Annotated

from pydantic import BeforeValidator
from sqlmodel import Field, SQLModel
from sqlmodel._compat import SQLModelConfig

from app.services.timestamps import utc_now_iso


class BookingStatusEnum(StrEnum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class PaymentArrangementEnum(StrEnum):
    PREPAID_DEFAULT = "PREPAID_DEFAULT"
    DELAYED_ALLOWED = "DELAYED_ALLOWED"
    PACKAGE_REDEEMED = "PACKAGE_REDEEMED"


class BookingPaymentStatusEnum(StrEnum):
    AWAITING_ACKNOWLEDGMENT = "AWAITING_ACKNOWLEDGMENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class GcalSyncStatusEnum(StrEnum):
    PENDING = "PENDING"
    SYNCED = "SYNCED"
    FAILED = "FAILED"
    NOT_CONFIGURED = "NOT_CONFIGURED"


BookingStatus = Annotated[
    BookingStatusEnum,
    BeforeValidator(lambda v: BookingStatusEnum(v) if isinstance(v, str) else v),
]

PaymentArrangement = Annotated[
    PaymentArrangementEnum,
    BeforeValidator(lambda v: PaymentArrangementEnum(v) if isinstance(v, str) else v),
]

BookingPaymentStatus = Annotated[
    BookingPaymentStatusEnum,
    BeforeValidator(lambda v: BookingPaymentStatusEnum(v) if isinstance(v, str) else v),
]

GcalSyncStatus = Annotated[
    GcalSyncStatusEnum,
    BeforeValidator(lambda v: GcalSyncStatusEnum(v) if isinstance(v, str) else v),
]


class Booking(SQLModel, table=True):
    model_config = SQLModelConfig(strict=True)
    __tablename__ = "bookings"  # pyright: ignore[reportAssignmentType]

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    booking_code: str = Field(unique=True, index=True)
    service_id: str = Field(foreign_key="services.id")
    client_id: str = Field(foreign_key="clients.id")
    package_id: str | None = Field(default=None, foreign_key="packages.id", index=True)
    scheduled_at: str = Field(index=True)
    duration_minutes: int = Field(default=60, ge=15)
    buffer_minutes: int = Field(default=0, ge=0)
    booking_status: BookingStatus = Field(default=BookingStatusEnum.RESERVED, index=True)
    payment_arrangement: PaymentArrangement = Field(default=PaymentArrangementEnum.PREPAID_DEFAULT)
    payment_status: BookingPaymentStatus = Field(
        default=BookingPaymentStatusEnum.AWAITING_ACKNOWLEDGMENT, index=True
    )
    amount_mxn: int = Field(ge=0)
    exception_authorized_by: str | None = Field(default=None, foreign_key="admin_allowlist.email")
    exception_authorized_at: str | None = None
    exception_notes: str | None = None
    released_by: str | None = Field(default=None, foreign_key="admin_allowlist.email")
    released_at: str | None = None
    release_reason: str | None = None
    acknowledged_by: str | None = Field(default=None, foreign_key="admin_allowlist.email")
    acknowledged_at: str | None = None
    gcal_event_id: str | None = None
    gcal_sync_status: GcalSyncStatus = Field(default=GcalSyncStatusEnum.PENDING)
    gcal_sync_error: str | None = None
    gcal_synced_at: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
