import uuid
from enum import StrEnum
from typing import Annotated

from pydantic import BeforeValidator
from sqlmodel import Field, SQLModel
from sqlmodel._compat import SQLModelConfig

from app.services.timestamps import utc_now_iso


class FinancialStatusEnum(StrEnum):
    PAID = "PAID"
    PARTIAL = "PARTIAL"
    PENDING = "PENDING"


FinancialStatus = Annotated[
    FinancialStatusEnum,
    BeforeValidator(lambda v: FinancialStatusEnum(v) if isinstance(v, str) else v),
]


class Package(SQLModel, table=True):
    model_config = SQLModelConfig(strict=True)
    __tablename__ = "packages"  # pyright: ignore[reportAssignmentType]

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    client_id: str = Field(foreign_key="clients.id", index=True)
    service_id: str = Field(foreign_key="services.id")
    total_sessions: int = Field(gt=0)
    completed_sessions: int = Field(default=0, ge=0)
    price_paid_mxn: int = Field(default=0, ge=0)
    financial_status: FinancialStatus = Field(default=FinancialStatusEnum.PENDING)
    notes: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
