from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import libsql_client
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import record_admin_audit, require_admin
from app.db.database import get_db, result_to_dicts, row_to_dict
from app.schemas.auth import AdminPrincipal
from app.schemas.booking import (
    BookingCompleteRequest,
    BookingCreate,
    BookingPaymentStatus,
    BookingRead,
    BookingReleaseRequest,
    BookingRescheduleRequest,
    BookingStatus,
    BookingStatusUpdateRequest,
    DelayedPaymentAuthorizeRequest,
    PaymentArrangement,
)
from app.services.bookings import (
    check_slot_collision,
    generate_booking_code,
    hydrate_booking_row,
)
from app.services.calendar import calendar_service
from app.services.timestamps import parse_iso_datetime

router = APIRouter(prefix="/bookings", tags=["Bookings"])

BOOKING_SELECT_QUERY = """
    SELECT
        b.id, b.booking_code, b.service_id, s.name AS service_name,
        b.client_id, c.full_name AS client_name, c.phone_whatsapp AS client_phone,
        b.package_id, b.scheduled_at, b.duration_minutes, b.buffer_minutes,
        b.booking_status, b.payment_arrangement, b.payment_status, b.amount_mxn,
        b.exception_authorized_by, b.exception_authorized_at, b.exception_notes,
        b.released_by, b.released_at, b.release_reason,
        b.acknowledged_by, b.acknowledged_at,
        b.gcal_event_id, b.gcal_sync_status, b.gcal_sync_error, b.gcal_synced_at,
        b.created_at
    FROM bookings b
    JOIN services s ON b.service_id = s.id
    JOIN clients c ON b.client_id = c.id
"""


async def _fetch_hydrated_booking(
    client: libsql_client.Client,
    booking_id: str,
    *,
    package_info: str | None = None,
) -> BookingRead:
    res = await client.execute(
        BOOKING_SELECT_QUERY + " WHERE b.id = ? LIMIT 1;",
        [booking_id],
    )
    if not res.rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    return hydrate_booking_row(row_to_dict(res, res.rows[0]), package_info=package_info)


@router.post("", response_model=BookingRead, status_code=status.HTTP_201_CREATED)
async def create_booking(payload: BookingCreate):
    """
    Create a reservation.
    Separates booking_status (RESERVED) from payment_arrangement (PREPAID_DEFAULT or PACKAGE_REDEEMED)
    and payment_status (AWAITING_ACKNOWLEDGMENT or NOT_APPLICABLE), enforcing mandatory buffer times
    and coordinating with Google Calendar.
    """
    async with get_db() as client:
        # 1. Fetch service details
        svc_res = await client.execute(
            "SELECT * FROM services WHERE id = ? AND is_active = 1 LIMIT 1;",
            [payload.service_id],
        )
        if not svc_res.rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Service not found or inactive",
            )
        service = row_to_dict(svc_res, svc_res.rows[0])
        duration_minutes = int(service.get("duration_minutes", 60))
        buffer_minutes = int(service.get("buffer_minutes", 0))
        max_capacity = int(service.get("max_capacity", 1))

        # 2. Collision & Buffer Check for INDIVIDUAL services, or Capacity check for GROUP
        new_start = parse_iso_datetime(payload.scheduled_at)
        if service["service_type"] == "INDIVIDUAL":
            active_res = await client.execute(
                """
                SELECT b.scheduled_at, b.duration_minutes, b.buffer_minutes
                FROM bookings b
                JOIN services s ON b.service_id = s.id
                WHERE b.booking_status = 'RESERVED' AND s.service_type = 'INDIVIDUAL';
                """
            )
            active_bookings = result_to_dicts(active_res)
            if check_slot_collision(new_start, duration_minutes, buffer_minutes, active_bookings):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Horario no disponible: Entra en conflicto con otra consulta o con el "
                        f"tiempo de colchón obligatorio ({buffer_minutes} min)."
                    ),
                )
        else:
            cap_res = await client.execute(
                """
                SELECT COUNT(*) AS count
                FROM bookings
                WHERE service_id = ? AND scheduled_at = ? AND booking_status = 'RESERVED';
                """,
                [service["id"], payload.scheduled_at],
            )
            current_count = int(str(cap_res.rows[0][0] or 0))
            if current_count >= max_capacity:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="El grupo ha alcanzado su cupo máximo para esta sesión.",
                )

        # 3. Upsert client
        client_res = await client.execute(
            "SELECT id FROM clients WHERE phone_whatsapp = ? LIMIT 1;",
            [payload.client_phone],
        )
        if client_res.rows:
            client_id = str(client_res.rows[0][0])
        else:
            client_id = str(uuid.uuid4())
            await client.execute(
                "INSERT INTO clients (id, full_name, phone_whatsapp, email, notes) VALUES (?, ?, ?, ?, ?);",
                [
                    client_id,
                    payload.client_name,
                    payload.client_phone,
                    payload.client_email,
                    payload.notes,
                ],
            )

        # 4. Determine payment arrangement and payment status
        now = datetime.now(UTC)
        package_info: str | None = None
        booking_status: BookingStatus = "RESERVED"

        if payload.package_id:
            pkg_res = await client.execute(
                "SELECT * FROM packages WHERE id = ? LIMIT 1;",
                [payload.package_id],
            )
            if not pkg_res.rows:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Paquete no encontrado"
                )
            package = row_to_dict(pkg_res, pkg_res.rows[0])
            completed = int(package["completed_sessions"])
            total = int(package["total_sessions"])
            if completed >= total:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El paquete ya no cuenta con sesiones disponibles",
                )

            await client.execute(
                "UPDATE packages SET completed_sessions = completed_sessions + 1, updated_at = ? WHERE id = ?;",
                [now.isoformat(), payload.package_id],
            )
            payment_arrangement: PaymentArrangement = "PACKAGE_REDEEMED"
            payment_status: BookingPaymentStatus = "NOT_APPLICABLE"
            amount_mxn = 0
            package_info = f"Sesión {completed + 1} de {total}"
        else:
            payment_arrangement = "PREPAID_DEFAULT"
            payment_status = "AWAITING_ACKNOWLEDGMENT"
            amount_mxn = int(service["price_mxn"])

        booking_id = str(uuid.uuid4())
        booking_code = generate_booking_code()

        # 5. Coordinate with Google Calendar (non-fatal on transient failure)
        cal_res = await calendar_service.sync_booking_event(
            booking_id=booking_id,
            booking_code=booking_code,
            service_name=str(service["name"]),
            client_name=payload.client_name,
            scheduled_at=payload.scheduled_at,
            duration_minutes=duration_minutes,
            booking_status=booking_status,
            payment_arrangement=payment_arrangement,
            payment_status=payment_status,
        )

        insert_booking_query = """
            INSERT INTO bookings (
                id, booking_code, service_id, client_id, package_id, scheduled_at,
                duration_minutes, buffer_minutes, booking_status, payment_arrangement,
                payment_status, amount_mxn, gcal_event_id, gcal_sync_status,
                gcal_sync_error, gcal_synced_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        await client.execute(
            insert_booking_query,
            [
                booking_id,
                booking_code,
                service["id"],
                client_id,
                payload.package_id,
                payload.scheduled_at,
                duration_minutes,
                buffer_minutes,
                booking_status,
                payment_arrangement,
                payment_status,
                amount_mxn,
                cal_res.event_id,
                cal_res.sync_status,
                cal_res.sync_error,
                cal_res.synced_at,
                now.isoformat(),
            ],
        )

        return await _fetch_hydrated_booking(client, booking_id, package_info=package_info)


@router.get("", response_model=list[BookingRead])
async def list_bookings(
    booking_status: BookingStatus | None = Query(None, alias="status"),
    payment_status: BookingPaymentStatus | None = None,
    payment_arrangement: PaymentArrangement | None = None,
    client_id: str | None = None,
    limit: int = 50,
    _admin: AdminPrincipal = Depends(require_admin),
):
    """Admin-facing endpoint to list bookings filtered by booking_status, payment_status, or arrangement."""
    query = BOOKING_SELECT_QUERY
    params: list[libsql_client.InValue] = []
    clauses: list[str] = []

    if booking_status:
        clauses.append("b.booking_status = ?")
        params.append(booking_status)
    if payment_status:
        clauses.append("b.payment_status = ?")
        params.append(payment_status)
    if payment_arrangement:
        clauses.append("b.payment_arrangement = ?")
        params.append(payment_arrangement)
    if client_id:
        clauses.append("b.client_id = ?")
        params.append(client_id)

    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    query += " ORDER BY b.scheduled_at ASC LIMIT ?;"
    params.append(limit)

    async with get_db() as client:
        res = await client.execute(query, params)
        rows = result_to_dicts(res)
        now = datetime.now(UTC)
        return [hydrate_booking_row(r, now=now) for r in rows]


@router.get("/follow-up-queue", response_model=list[BookingRead])
async def get_payment_followup_queue(
    window_hours: int = Query(default=48, ge=1, le=720),
    _admin: AdminPrincipal = Depends(require_admin),
):
    """
    Dedicated operational visibility queue for Jasmin and her assistant.
    Returns bookings with unacknowledged payment (`AWAITING_ACKNOWLEDGMENT`) that are either:
    1. Active (`RESERVED`) and scheduled within `window_hours` (default 48h), OR
    2. Authorized for delayed payment (`DELAYED_ALLOWED`) and still awaiting settlement.
    """
    query = (
        BOOKING_SELECT_QUERY
        + """
        WHERE b.payment_status = 'AWAITING_ACKNOWLEDGMENT'
          AND b.booking_status IN ('RESERVED', 'COMPLETED')
        ORDER BY b.scheduled_at ASC;
        """
    )
    async with get_db() as client:
        res = await client.execute(query)
        rows = result_to_dicts(res)
        now = datetime.now(UTC)
        hydrated = [hydrate_booking_row(r, now=now, window_hours=window_hours) for r in rows]
        return [b for b in hydrated if b.needs_payment_followup]


@router.post("/{booking_id}/authorize-delayed-payment", response_model=BookingRead)
async def authorize_delayed_payment(
    booking_id: str,
    payload: DelayedPaymentAuthorizeRequest,
    admin: AdminPrincipal = Depends(require_admin),
):
    """
    Authorized administrative exception: allow a session to proceed without prepayment.
    Sets payment_arrangement = 'DELAYED_ALLOWED', records who authorized the exception and when,
    and keeps payment_status = 'AWAITING_ACKNOWLEDGMENT' so the delayed payment remains traceable.
    """
    async with get_db() as client:
        res = await client.execute(
            BOOKING_SELECT_QUERY + " WHERE b.id = ? LIMIT 1;",
            [booking_id],
        )
        if not res.rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
        booking = row_to_dict(res, res.rows[0])

        if booking["booking_status"] in ("RELEASED", "CANCELLED"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot authorize delayed payment on a released or cancelled booking.",
            )
        if booking["payment_status"] == "ACKNOWLEDGED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment for this booking has already been acknowledged.",
            )

        now = datetime.now(UTC).isoformat()
        cal_res = await calendar_service.sync_booking_event(
            booking_id=booking_id,
            booking_code=str(booking["booking_code"]),
            service_name=str(booking["service_name"]),
            client_name=str(booking["client_name"]),
            scheduled_at=str(booking["scheduled_at"]),
            duration_minutes=int(booking["duration_minutes"]),
            booking_status=str(booking["booking_status"]),
            payment_arrangement="DELAYED_ALLOWED",
            payment_status="AWAITING_ACKNOWLEDGMENT",
            existing_event_id=booking.get("gcal_event_id"),
        )

        await client.execute(
            """
            UPDATE bookings
            SET payment_arrangement = 'DELAYED_ALLOWED',
                payment_status = 'AWAITING_ACKNOWLEDGMENT',
                exception_authorized_by = ?,
                exception_authorized_at = ?,
                exception_notes = ?,
                gcal_event_id = ?,
                gcal_sync_status = ?,
                gcal_sync_error = ?,
                gcal_synced_at = ?
            WHERE id = ?;
            """,
            [
                admin.email,
                now,
                payload.notes,
                cal_res.event_id,
                cal_res.sync_status,
                cal_res.sync_error,
                cal_res.synced_at,
                booking_id,
            ],
        )

        await record_admin_audit(
            client,
            admin_email=admin.email,
            action_type="AUTHORIZE_DELAYED_PAYMENT",
            entity_type="booking",
            entity_id=booking_id,
            details={"booking_code": booking["booking_code"], "notes": payload.notes},
        )
        return await _fetch_hydrated_booking(client, booking_id)


@router.post("/{booking_id}/release", response_model=BookingRead)
async def release_booking_slot(
    booking_id: str,
    payload: BookingReleaseRequest,
    admin: AdminPrincipal = Depends(require_admin),
):
    """
    Deliberate administrative action to release a booking slot so another client can take the place.
    Bookings never expire automatically; only an authorized administrator can release a slot.
    """
    async with get_db() as client:
        res = await client.execute(
            BOOKING_SELECT_QUERY + " WHERE b.id = ? LIMIT 1;",
            [booking_id],
        )
        if not res.rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
        booking = row_to_dict(res, res.rows[0])

        if booking["booking_status"] == "RELEASED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Booking slot has already been released.",
            )

        now = datetime.now(UTC).isoformat()
        new_payment_status = (
            "NOT_APPLICABLE"
            if booking["payment_status"] == "AWAITING_ACKNOWLEDGMENT"
            else booking["payment_status"]
        )

        cal_res = await calendar_service.sync_booking_event(
            booking_id=booking_id,
            booking_code=str(booking["booking_code"]),
            service_name=str(booking["service_name"]),
            client_name=str(booking["client_name"]),
            scheduled_at=str(booking["scheduled_at"]),
            duration_minutes=int(booking["duration_minutes"]),
            booking_status="RELEASED",
            payment_arrangement=str(booking["payment_arrangement"]),
            payment_status=str(new_payment_status),
            existing_event_id=booking.get("gcal_event_id"),
        )

        await client.execute(
            """
            UPDATE bookings
            SET booking_status = 'RELEASED',
                payment_status = ?,
                released_by = ?,
                released_at = ?,
                release_reason = ?,
                gcal_event_id = ?,
                gcal_sync_status = ?,
                gcal_sync_error = ?,
                gcal_synced_at = ?
            WHERE id = ?;
            """,
            [
                new_payment_status,
                admin.email,
                now,
                payload.reason,
                cal_res.event_id,
                cal_res.sync_status,
                cal_res.sync_error,
                cal_res.synced_at,
                booking_id,
            ],
        )

        await record_admin_audit(
            client,
            admin_email=admin.email,
            action_type="RELEASE_BOOKING",
            entity_type="booking",
            entity_id=booking_id,
            details={"booking_code": booking["booking_code"], "reason": payload.reason},
        )
        return await _fetch_hydrated_booking(client, booking_id)


@router.post("/{booking_id}/status", response_model=BookingRead)
async def update_booking_status(
    booking_id: str,
    payload: BookingStatusUpdateRequest,
    admin: AdminPrincipal = Depends(require_admin),
):
    """
    Transition booking_status to COMPLETED, CANCELLED, or NO_SHOW.
    Crucially, marking a booking COMPLETED does NOT implicitly mark an unpaid delayed payment as ACKNOWLEDGED.
    """
    async with get_db() as client:
        res = await client.execute(
            BOOKING_SELECT_QUERY + " WHERE b.id = ? LIMIT 1;",
            [booking_id],
        )
        if not res.rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
        booking = row_to_dict(res, res.rows[0])

        new_payment_status = str(booking["payment_status"])
        if (
            payload.booking_status == "CANCELLED"
            and new_payment_status == "AWAITING_ACKNOWLEDGMENT"
            and booking["payment_arrangement"] == "PREPAID_DEFAULT"
        ):
            new_payment_status = "NOT_APPLICABLE"

        cal_res = await calendar_service.sync_booking_event(
            booking_id=booking_id,
            booking_code=str(booking["booking_code"]),
            service_name=str(booking["service_name"]),
            client_name=str(booking["client_name"]),
            scheduled_at=str(booking["scheduled_at"]),
            duration_minutes=int(booking["duration_minutes"]),
            booking_status=payload.booking_status,
            payment_arrangement=str(booking["payment_arrangement"]),
            payment_status=new_payment_status,
            existing_event_id=booking.get("gcal_event_id"),
        )

        await client.execute(
            """
            UPDATE bookings
            SET booking_status = ?,
                payment_status = ?,
                gcal_event_id = ?,
                gcal_sync_status = ?,
                gcal_sync_error = ?,
                gcal_synced_at = ?
            WHERE id = ?;
            """,
            [
                payload.booking_status,
                new_payment_status,
                cal_res.event_id,
                cal_res.sync_status,
                cal_res.sync_error,
                cal_res.synced_at,
                booking_id,
            ],
        )

        await record_admin_audit(
            client,
            admin_email=admin.email,
            action_type="UPDATE_BOOKING_STATUS",
            entity_type="booking",
            entity_id=booking_id,
            details={
                "booking_code": booking["booking_code"],
                "new_status": payload.booking_status,
                "notes": payload.notes,
            },
        )
        return await _fetch_hydrated_booking(client, booking_id)


@router.post("/{booking_id}/sync-calendar", response_model=BookingRead)
async def retry_calendar_sync(
    booking_id: str,
    admin: AdminPrincipal = Depends(require_admin),
):
    """Manually retry Google Calendar synchronization for a booking."""
    async with get_db() as client:
        res = await client.execute(
            BOOKING_SELECT_QUERY + " WHERE b.id = ? LIMIT 1;",
            [booking_id],
        )
        if not res.rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
        booking = row_to_dict(res, res.rows[0])

        cal_res = await calendar_service.sync_booking_event(
            booking_id=booking_id,
            booking_code=str(booking["booking_code"]),
            service_name=str(booking["service_name"]),
            client_name=str(booking["client_name"]),
            scheduled_at=str(booking["scheduled_at"]),
            duration_minutes=int(booking["duration_minutes"]),
            booking_status=str(booking["booking_status"]),
            payment_arrangement=str(booking["payment_arrangement"]),
            payment_status=str(booking["payment_status"]),
            existing_event_id=booking.get("gcal_event_id"),
        )

        await client.execute(
            """
            UPDATE bookings
            SET gcal_event_id = ?,
                gcal_sync_status = ?,
                gcal_sync_error = ?,
                gcal_synced_at = ?
            WHERE id = ?;
            """,
            [
                cal_res.event_id,
                cal_res.sync_status,
                cal_res.sync_error,
                cal_res.synced_at,
                booking_id,
            ],
        )

        await record_admin_audit(
            client,
            admin_email=admin.email,
            action_type="RETRY_CALENDAR_SYNC",
            entity_type="booking",
            entity_id=booking_id,
            details={"sync_status": cal_res.sync_status, "sync_error": cal_res.sync_error},
        )
        return await _fetch_hydrated_booking(client, booking_id)


@router.post("/{booking_id}/reschedule", response_model=BookingRead)
async def reschedule_booking(
    booking_id: str,
    payload: BookingRescheduleRequest,
    admin: AdminPrincipal = Depends(require_admin),
):
    """
    Reschedule an existing RESERVED booking to a new datetime.
    Validates slot collision factoring in mandatory buffer times, updates Google Calendar,
    and returns hydrated booking with updated WhatsApp deep link.
    """
    async with get_db() as client:
        # 1. Fetch current booking
        res = await client.execute(
            BOOKING_SELECT_QUERY + " WHERE b.id = ? LIMIT 1;",
            [booking_id],
        )
        if not res.rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
        booking = row_to_dict(res, res.rows[0])

        # 2. Validate booking_status is RESERVED
        if booking["booking_status"] != "RESERVED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot reschedule booking with status {booking['booking_status']}. Only RESERVED bookings can be rescheduled.",
            )

        # 3. Fetch service to check INDIVIDUAL vs GROUP, buffer, and duration
        svc_res = await client.execute(
            "SELECT * FROM services WHERE id = ? LIMIT 1;",
            [booking["service_id"]],
        )
        if not svc_res.rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
        service = row_to_dict(svc_res, svc_res.rows[0])

        duration_minutes = int(
            booking.get("duration_minutes") or service.get("duration_minutes", 60)
        )
        buffer_minutes = int(booking.get("buffer_minutes") or service.get("buffer_minutes", 0))
        max_capacity = int(service.get("max_capacity", 1))

        # 4. Collision check factoring in buffer
        new_start = parse_iso_datetime(payload.new_scheduled_at)
        if service["service_type"] == "INDIVIDUAL":
            active_res = await client.execute(
                """
                SELECT b.id, b.scheduled_at, b.duration_minutes, b.buffer_minutes
                FROM bookings b
                JOIN services s ON b.service_id = s.id
                WHERE b.booking_status = 'RESERVED' AND s.service_type = 'INDIVIDUAL' AND b.id != ?;
                """,
                [booking_id],
            )
            active_bookings = result_to_dicts(active_res)
            if check_slot_collision(new_start, duration_minutes, buffer_minutes, active_bookings):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Horario no disponible: Entra en conflicto con otra consulta o con el "
                        f"tiempo de colchón obligatorio ({buffer_minutes} min)."
                    ),
                )
        else:
            cap_res = await client.execute(
                """
                SELECT COUNT(*) AS count
                FROM bookings
                WHERE service_id = ? AND scheduled_at = ? AND booking_status = 'RESERVED' AND id != ?;
                """,
                [service["id"], payload.new_scheduled_at, booking_id],
            )
            current_count = int(str(cap_res.rows[0][0] or 0))
            if current_count >= max_capacity:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="El grupo ha alcanzado su cupo máximo para esta sesión.",
                )

        # 5. Sync with Google Calendar
        cal_res = await calendar_service.sync_booking_event(
            booking_id=booking_id,
            booking_code=str(booking["booking_code"]),
            service_name=str(booking["service_name"]),
            client_name=str(booking["client_name"]),
            scheduled_at=payload.new_scheduled_at,
            duration_minutes=duration_minutes,
            booking_status="RESERVED",
            payment_arrangement=str(booking["payment_arrangement"]),
            payment_status=str(booking["payment_status"]),
            existing_event_id=booking.get("gcal_event_id"),
        )

        # 6. Update booking scheduled_at and sync state
        await client.execute(
            """
            UPDATE bookings
            SET scheduled_at = ?,
                gcal_event_id = ?,
                gcal_sync_status = ?,
                gcal_sync_error = ?,
                gcal_synced_at = ?
            WHERE id = ?;
            """,
            [
                payload.new_scheduled_at,
                cal_res.event_id,
                cal_res.sync_status,
                cal_res.sync_error,
                cal_res.synced_at,
                booking_id,
            ],
        )

        # 7. Record admin audit log
        await record_admin_audit(
            client,
            admin_email=admin.email,
            action_type="RESCHEDULE_BOOKING",
            entity_type="booking",
            entity_id=booking_id,
            details={
                "booking_code": booking["booking_code"],
                "previous_scheduled_at": booking["scheduled_at"],
                "new_scheduled_at": payload.new_scheduled_at,
                "notes": payload.notes,
            },
        )

        # 8. Package info if applicable
        package_info = None
        if booking.get("package_id"):
            pkg_res = await client.execute(
                "SELECT * FROM packages WHERE id = ? LIMIT 1;",
                [booking["package_id"]],
            )
            if pkg_res.rows:
                pkg_row = row_to_dict(pkg_res, pkg_res.rows[0])
                package_info = (
                    f"Sesión {pkg_row['completed_sessions']} de {pkg_row['total_sessions']}"
                )

        return await _fetch_hydrated_booking(client, booking_id, package_info=package_info)


@router.post("/{booking_id}/complete", response_model=BookingRead)
async def complete_booking(
    booking_id: str,
    payload: BookingCompleteRequest | None = None,
    admin: AdminPrincipal = Depends(require_admin),
):
    """
    Mark consultation session as COMPLETED.
    Records package session completion if linked to a multi-session package,
    updates Google Calendar, and records admin audit log.
    """
    async with get_db() as client:
        # 1. Fetch current booking
        res = await client.execute(
            BOOKING_SELECT_QUERY + " WHERE b.id = ? LIMIT 1;",
            [booking_id],
        )
        if not res.rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
        booking = row_to_dict(res, res.rows[0])

        # 2. Validate booking_status is RESERVED
        if booking["booking_status"] != "RESERVED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot complete booking with status {booking['booking_status']}. Only RESERVED bookings can be marked as COMPLETED.",
            )

        now = datetime.now(UTC).isoformat()
        notes = payload.notes if payload else None
        target_pkg_id = (
            payload.package_id if (payload and payload.package_id) else booking.get("package_id")
        )
        package_counter_advanced = False

        # If a new package is linked during completion, advance counter and update payment arrangement
        if payload and payload.package_id and booking.get("package_id") != payload.package_id:
            pkg_res = await client.execute(
                "SELECT * FROM packages WHERE id = ? LIMIT 1;",
                [payload.package_id],
            )
            if not pkg_res.rows:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Package not found"
                )
            pkg_row = row_to_dict(pkg_res, pkg_res.rows[0])
            completed = int(pkg_row["completed_sessions"])
            total = int(pkg_row["total_sessions"])
            if completed >= total:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El paquete ya no cuenta con sesiones disponibles",
                )
            await client.execute(
                "UPDATE packages SET completed_sessions = completed_sessions + 1, updated_at = ? WHERE id = ?;",
                [now, payload.package_id],
            )
            package_counter_advanced = True
            await client.execute(
                """
                UPDATE bookings
                SET package_id = ?, payment_arrangement = 'PACKAGE_REDEEMED', payment_status = 'NOT_APPLICABLE'
                WHERE id = ?;
                """,
                [payload.package_id, booking_id],
            )
            booking["package_id"] = payload.package_id
            booking["payment_arrangement"] = "PACKAGE_REDEEMED"
            booking["payment_status"] = "NOT_APPLICABLE"

        # 3. Google Calendar sync
        cal_res = await calendar_service.sync_booking_event(
            booking_id=booking_id,
            booking_code=str(booking["booking_code"]),
            service_name=str(booking["service_name"]),
            client_name=str(booking["client_name"]),
            scheduled_at=str(booking["scheduled_at"]),
            duration_minutes=int(booking["duration_minutes"]),
            booking_status="COMPLETED",
            payment_arrangement=str(booking["payment_arrangement"]),
            payment_status=str(booking["payment_status"]),
            existing_event_id=booking.get("gcal_event_id"),
        )

        # 4. Update booking_status = COMPLETED
        await client.execute(
            """
            UPDATE bookings
            SET booking_status = 'COMPLETED',
                gcal_event_id = ?,
                gcal_sync_status = ?,
                gcal_sync_error = ?,
                gcal_synced_at = ?
            WHERE id = ?;
            """,
            [
                cal_res.event_id,
                cal_res.sync_status,
                cal_res.sync_error,
                cal_res.synced_at,
                booking_id,
            ],
        )

        # 5. Admin audit log
        audit_details: dict[str, Any] = {
            "booking_code": booking["booking_code"],
            "notes": notes,
        }
        if target_pkg_id:
            audit_details["package_id"] = target_pkg_id
            audit_details["package_session_completed"] = True
            if package_counter_advanced:
                audit_details["package_counter_advanced"] = True
            await record_admin_audit(
                client,
                admin_email=admin.email,
                action_type="COMPLETE_PACKAGE_SESSION",
                entity_type="package",
                entity_id=target_pkg_id,
                details={"booking_id": booking_id, "booking_code": booking["booking_code"]},
            )

        await record_admin_audit(
            client,
            admin_email=admin.email,
            action_type="COMPLETE_BOOKING",
            entity_type="booking",
            entity_id=booking_id,
            details=audit_details,
        )

        package_info = None
        if target_pkg_id:
            pkg_res = await client.execute(
                "SELECT * FROM packages WHERE id = ? LIMIT 1;", [target_pkg_id]
            )
            if pkg_res.rows:
                pkg_row = row_to_dict(pkg_res, pkg_res.rows[0])
                package_info = (
                    f"Sesión {pkg_row['completed_sessions']} de {pkg_row['total_sessions']}"
                )

        return await _fetch_hydrated_booking(client, booking_id, package_info=package_info)
