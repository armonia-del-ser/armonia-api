from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PaymentMethod = Literal["SPEI", "OXXO", "CASH"]
PaymentStatus = Literal["ACKNOWLEDGED", "REVERSED"]


class PaymentAcknowledgmentRequest(BaseModel):
    booking_id: str
    amount_mxn: int = Field(..., ge=0)
    payment_method: PaymentMethod = "SPEI"
    notes: str | None = None


# Alias for backward compatibility
PaymentVerificationRequest = PaymentAcknowledgmentRequest


class PaymentRead(BaseModel):
    id: str
    booking_id: str
    amount_mxn: int
    payment_method: PaymentMethod
    status: PaymentStatus
    acknowledged_by: str
    acknowledged_at: str
    notes: str | None = None
    created_at: str
