from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PaymentMethod = Literal["SPEI", "OXXO", "CASH"]
PaymentStatus = Literal["PENDING", "VERIFIED", "REJECTED"]


class PaymentVerificationRequest(BaseModel):
    booking_id: str
    amount_mxn: int = Field(..., ge=0)
    payment_method: PaymentMethod = "SPEI"
    notes: str | None = None


class PaymentRead(BaseModel):
    id: str
    booking_id: str
    amount_mxn: int
    payment_method: PaymentMethod
    status: PaymentStatus
    verified_at: str | None = None
    notes: str | None = None
    created_at: str
