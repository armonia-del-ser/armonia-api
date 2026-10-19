from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ServiceBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    description: str | None = None
    service_type: Literal["GROUP", "INDIVIDUAL"]
    modality: Literal["PRESENCIAL", "ONLINE"]
    default_schedule: str | None = None
    price_mxn: int = Field(..., ge=0)
    max_capacity: int = Field(default=1, ge=1)
    duration_minutes: int = Field(default=60, ge=15)
    buffer_minutes: int = Field(default=0, ge=0)
    is_active: bool = True


class ServiceCreate(ServiceBase):
    slug: str = Field(..., min_length=2, max_length=100)


class ServiceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    service_type: Literal["GROUP", "INDIVIDUAL"] | None = None
    modality: Literal["PRESENCIAL", "ONLINE"] | None = None
    default_schedule: str | None = None
    price_mxn: int | None = Field(default=None, ge=0)
    max_capacity: int | None = Field(default=None, ge=1)
    duration_minutes: int | None = Field(default=None, ge=15)
    buffer_minutes: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class ServiceRead(ServiceBase):
    id: str
    slug: str
    created_at: str
