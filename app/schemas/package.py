from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FinancialStatus = Literal["PAID", "PARTIAL", "PENDING"]


class PackageBase(BaseModel):
    client_id: str
    service_id: str
    total_sessions: int = Field(..., ge=1, description="Total sessions in package, e.g. 5 or 10")
    price_paid_mxn: int = Field(default=0, ge=0)
    financial_status: FinancialStatus = "PENDING"
    notes: str | None = None


class PackageCreate(PackageBase):
    completed_sessions: int = Field(default=0, ge=0)


class PackageUpdate(BaseModel):
    total_sessions: int | None = Field(default=None, ge=1)
    completed_sessions: int | None = Field(default=None, ge=0)
    price_paid_mxn: int | None = Field(default=None, ge=0)
    financial_status: FinancialStatus | None = None
    notes: str | None = None


class PackageRedeem(BaseModel):
    scheduled_at: str = Field(..., description="ISO 8601 string for the redeemed session date/time")
    notes: str | None = None


class PackageRead(PackageBase):
    id: str
    completed_sessions: int
    remaining_sessions: int
    client_name: str | None = None
    client_phone: str | None = None
    service_name: str | None = None
    created_at: str
    updated_at: str
