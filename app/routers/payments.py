from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status

from app.db.database import get_db, result_to_dicts, row_to_dict
from app.schemas.payment import PaymentRead, PaymentVerificationRequest

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post("/verify", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
async def verify_payment(payload: PaymentVerificationRequest):
    """
    Admin-facing action: Jazmín confirms receipt of SPEI/OXXO deposit.
    Locks in the booking, changes status to CONFIRMED, and records the payment.
    """
    async with get_db() as client:
        # 1. Fetch booking
        b_res = await client.execute(
            "SELECT * FROM bookings WHERE id = ? LIMIT 1;",
            [payload.booking_id],
        )
        if not b_res.rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

        booking = row_to_dict(b_res, b_res.rows[0])
        if booking["status"] == "CONFIRMED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Booking is already confirmed",
            )

        now = datetime.now(UTC).isoformat()
        payment_id = str(uuid.uuid4())

        # 2. Record payment
        await client.execute(
            """
            INSERT INTO payments (id, booking_id, amount_mxn, payment_method, status, verified_at, notes, created_at)
            VALUES (?, ?, ?, ?, 'VERIFIED', ?, ?, ?);
            """,
            [
                payment_id,
                payload.booking_id,
                payload.amount_mxn,
                payload.payment_method,
                now,
                payload.notes,
                now,
            ],
        )

        # 3. Transition booking to CONFIRMED
        await client.execute(
            "UPDATE bookings SET status = 'CONFIRMED', confirmed_at = ? WHERE id = ?;",
            [now, payload.booking_id],
        )

        return PaymentRead(
            id=payment_id,
            booking_id=payload.booking_id,
            amount_mxn=payload.amount_mxn,
            payment_method=payload.payment_method,
            status="VERIFIED",
            verified_at=now,
            notes=payload.notes,
            created_at=now,
        )


@router.get("/history", response_model=list[PaymentRead])
async def list_payments(limit: int = 50):
    """List recent verified payment records."""
    async with get_db() as client:
        res = await client.execute(
            "SELECT * FROM payments ORDER BY created_at DESC LIMIT ?;",
            [limit],
        )
        rows = result_to_dicts(res)
        return [PaymentRead(**r) for r in rows]
