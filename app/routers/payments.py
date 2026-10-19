from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import record_admin_audit, require_admin
from app.db.database import get_db, result_to_dicts, row_to_dict
from app.routers.bookings import BOOKING_SELECT_QUERY
from app.schemas.auth import AdminPrincipal
from app.schemas.payment import PaymentAcknowledgmentRequest, PaymentRead
from app.services.calendar import calendar_service

router = APIRouter(prefix="/payments", tags=["Payments"])


async def _acknowledge_payment_impl(
    payload: PaymentAcknowledgmentRequest,
    admin: AdminPrincipal,
) -> PaymentRead:
    async with get_db() as client:
        # 1. Fetch hydrated booking details
        b_res = await client.execute(
            BOOKING_SELECT_QUERY + " WHERE b.id = ? LIMIT 1;",
            [payload.booking_id],
        )
        if not b_res.rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

        booking = row_to_dict(b_res, b_res.rows[0])
        if booking["payment_status"] == "ACKNOWLEDGED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment for this booking has already been acknowledged",
            )
        if booking["booking_status"] in ("RELEASED", "CANCELLED"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot acknowledge payment on a released or cancelled booking",
            )

        now = datetime.now(UTC).isoformat()
        payment_id = str(uuid.uuid4())

        # 2. Record payment acknowledgment
        await client.execute(
            """
            INSERT INTO payments (
                id, booking_id, amount_mxn, payment_method, status,
                acknowledged_by, acknowledged_at, notes, created_at
            )
            VALUES (?, ?, ?, ?, 'ACKNOWLEDGED', ?, ?, ?, ?);
            """,
            [
                payment_id,
                payload.booking_id,
                payload.amount_mxn,
                payload.payment_method,
                admin.email,
                now,
                payload.notes,
                now,
            ],
        )

        # 3. Sync Google Calendar event to [CONFIRMADO]
        cal_res = await calendar_service.sync_booking_event(
            booking_id=payload.booking_id,
            booking_code=str(booking["booking_code"]),
            service_name=str(booking["service_name"]),
            client_name=str(booking["client_name"]),
            scheduled_at=str(booking["scheduled_at"]),
            duration_minutes=int(booking["duration_minutes"]),
            booking_status=str(booking["booking_status"]),
            payment_arrangement=str(booking["payment_arrangement"]),
            payment_status="ACKNOWLEDGED",
            existing_event_id=booking.get("gcal_event_id"),
        )

        # 4. Update booking payment_status and audit fields
        await client.execute(
            """
            UPDATE bookings
            SET payment_status = 'ACKNOWLEDGED',
                acknowledged_by = ?,
                acknowledged_at = ?,
                gcal_event_id = ?,
                gcal_sync_status = ?,
                gcal_sync_error = ?,
                gcal_synced_at = ?
            WHERE id = ?;
            """,
            [
                admin.email,
                now,
                cal_res.event_id,
                cal_res.sync_status,
                cal_res.sync_error,
                cal_res.synced_at,
                payload.booking_id,
            ],
        )

        # 5. Record audit log
        await record_admin_audit(
            client,
            admin_email=admin.email,
            action_type="ACKNOWLEDGE_PAYMENT",
            entity_type="booking",
            entity_id=payload.booking_id,
            details={
                "payment_id": payment_id,
                "amount_mxn": payload.amount_mxn,
                "payment_method": payload.payment_method,
                "notes": payload.notes,
            },
        )

        return PaymentRead(
            id=payment_id,
            booking_id=payload.booking_id,
            amount_mxn=payload.amount_mxn,
            payment_method=payload.payment_method,
            status="ACKNOWLEDGED",
            acknowledged_by=admin.email,
            acknowledged_at=now,
            notes=payload.notes,
            created_at=now,
        )


@router.post("/acknowledge", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
async def acknowledge_payment(
    payload: PaymentAcknowledgmentRequest,
    admin: AdminPrincipal = Depends(require_admin),
):
    """
    Admin-facing action: Jasmin or her assistant acknowledges receipt of SPEI/cash payment.
    Records who acknowledged the payment and when, transitions payment_status to ACKNOWLEDGED,
    and updates the Google Calendar event to [CONFIRMADO].
    """
    return await _acknowledge_payment_impl(payload, admin)


@router.post("/verify", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
async def verify_payment_alias(
    payload: PaymentAcknowledgmentRequest,
    admin: AdminPrincipal = Depends(require_admin),
):
    """Alias for /payments/acknowledge."""
    return await _acknowledge_payment_impl(payload, admin)


@router.get("/history", response_model=list[PaymentRead])
async def list_payments(
    limit: int = 50,
    _admin: AdminPrincipal = Depends(require_admin),
):
    """List recent acknowledged payment records."""
    async with get_db() as client:
        res = await client.execute(
            "SELECT * FROM payments ORDER BY created_at DESC LIMIT ?;",
            [limit],
        )
        rows = result_to_dicts(res)
        return [PaymentRead(**r) for r in rows]
