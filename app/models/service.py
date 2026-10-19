from enum import StrEnum
from typing import Annotated

from pydantic import BeforeValidator
from sqlmodel import Field, SQLModel
from sqlmodel._compat import SQLModelConfig

from app.services.timestamps import utc_now_iso


class ServiceTypeEnum(StrEnum):
    GROUP = "GROUP"
    INDIVIDUAL = "INDIVIDUAL"


class ServiceModalityEnum(StrEnum):
    PRESENCIAL = "PRESENCIAL"
    ONLINE = "ONLINE"


ServiceType = Annotated[
    ServiceTypeEnum, BeforeValidator(lambda v: ServiceTypeEnum(v) if isinstance(v, str) else v)
]

ServiceModality = Annotated[
    ServiceModalityEnum,
    BeforeValidator(lambda v: ServiceModalityEnum(v) if isinstance(v, str) else v),
]


class Service(SQLModel, table=True):
    model_config = SQLModelConfig(strict=True)
    __tablename__ = "services"  # pyright: ignore[reportAssignmentType]
    id: str | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    description: str | None = None
    service_type: ServiceType
    modality: ServiceModality
    default_schedule: str | None = None
    price_mxn: int = Field(default=0, ge=0)
    max_capacity: int = Field(default=1, ge=1)
    duration_minutes: int = Field(default=60, ge=15)
    buffer_minutes: int = Field(default=15, ge=0)
    is_active: bool = Field(default=True)
    created_at: str = Field(default_factory=utc_now_iso)
