import uuid
from enum import StrEnum
from typing import Annotated

from pydantic import BeforeValidator
from sqlmodel import Field, SQLModel
from sqlmodel._compat import SQLModelConfig

from app.services.timestamps import utc_now_iso


class PaymentMethodEnum(StrEnum):
    SPEI = "SPEI"
    OXXO = "OXXO"
    CASH = "CASH"


class PaymentStatusEnum(StrEnum):
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REVERSED = "REVERSED"


PaymentMethod = Annotated[
    PaymentMethodEnum,
    BeforeValidator(lambda v: PaymentMethodEnum(v) if isinstance(v, str) else v),
]

PaymentStatus = Annotated[
    PaymentStatusEnum,
    BeforeValidator(lambda v: PaymentStatusEnum(v) if isinstance(v, str) else v),
]


class Payment(SQLModel, table=True):
    model_config = SQLModelConfig(strict=True)
    __tablename__ = "payments"  # pyright: ignore[reportAssignmentType]

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    booking_id: str = Field(foreign_key="bookings.id")
    amount_mxn: int = Field(ge=0)
    payment_method: PaymentMethod = Field(default=PaymentMethodEnum.SPEI)
    status: PaymentStatus = Field(default=PaymentStatusEnum.ACKNOWLEDGED)
    acknowledged_by: str = Field(foreign_key="admin_allowlist.email")
    acknowledged_at: str
    notes: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
