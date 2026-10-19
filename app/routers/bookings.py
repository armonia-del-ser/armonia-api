from __future__ import annotations

import secrets
import urllib.parse
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import libsql_client
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import record_admin_audit, require_admin
from app.core.config import settings
from app.db.database import get_db, result_to_dicts, row_to_dict
from app.schemas.auth import AdminPrincipal
from app.schemas.booking import (
    BookingCreate,
    BookingPaymentStatus,
    BookingRead,
    BookingReleaseRequest,
    BookingStatus,
    BookingStatusUpdateRequest,
    DelayedPaymentAuthorizeRequest,
    PaymentArrangement,
)
from app.services.calendar import calendar_service

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


def parse_iso_datetime(dt_str: str) -> datetime:
    """Parse an ISO 8601 string, normalizing naive datetimes to UTC."""
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def check_slot_collision(
    new_start: datetime,
    new_duration: int,
    new_buffer: int,
    existing_bookings: list[dict[str, Any]],
) -> bool:
    """
    Returns True if the requested slot interval (including mandatory buffer)
    collides with any existing RESERVED booking interval (including its buffer).
    Formula: max(A_start, B_start) < min(A_blocked_end, B_blocked_end)
    """
    new_blocked_end = new_start + timedelta(minutes=new_duration + new_buffer)
    for b in existing_bookings:
        exist_start = parse_iso_datetime(str(b["scheduled_at"]))
        exist_duration = int(b.get("duration_minutes", 60))
        exist_buffer = int(b.get("buffer_minutes", 0))
        exist_blocked_end = exist_start + timedelta(minutes=exist_duration + exist_buffer)

        if new_start < exist_blocked_end and exist_start < new_blocked_end:
            return True
    return False


def generate_booking_code() -> str:
    """Generate a clean human-readable folio code, e.g. ADS-7F2A."""
    token = secrets.token_hex(2).upper()
    return f"ADS-{token}"


def build_whatsapp_link(
    service_name: str,
    scheduled_at: str,
    folio: str,
    amount_mxn: int,
    package_info: str | None = None,
) -> str:
    """Generate a pre-filled WhatsApp link for the client to message Armonía del Ser."""
    if package_info:
        msg = (
            f"Hola {settings.therapist_name}! ✨ Agendé mi sesión ({package_info}) para *{service_name}* "
            f"para el {scheduled_at}.\n\n"
            f"📌 *Folio de cita:* {folio}\n"
            f"¡Nos vemos pronto!"
        )
    else:
        msg = (
            f"Hola {settings.therapist_name}! ✨ Acabo de apartar mi lugar para *{service_name}* "
            f"para el {scheduled_at}.\n\n"
            f"📌 *Folio de reserva:* {folio}\n"
            f"💰 *Monto a transferir:* ${amount_mxn} MXN\n"
            f"🏦 *Banco:* {settings.spei_bank}\n"
            f"💳 *CLABE:* {settings.spei_clabe}\n"
            f"👤 *Beneficiario:* {settings.spei_beneficiary}\n\n"
            f"Te adjunto mi comprobante de pago en este chat para confirmar mi lugar. ¡Muchas gracias!"
        )
    encoded = urllib.parse.quote(msg)
    clean_phone = settings.whatsapp_phone.replace("+", "").replace(" ", "").replace("-", "")
    return f"https://wa.me/{clean_phone}?text={encoded}"


def build_assistant_followup_link(
    client_name: str,
    client_phone: str,
    service_name: str,
    scheduled_at: str,
    folio: str,
    amount_mxn: int,
) -> str:
    """Generate a pre-filled WhatsApp link for Jasmin's assistant to follow up with the client."""
    msg = (
        f"Hola {client_name}, te escribimos de *{settings.business_name}* respecto a tu espacio "
        f"reservado para *{service_name}* el {scheduled_at} (Folio *{folio}*, ${amount_mxn} MXN).\n\n"
        f"¿Nos confirmas si realizarás tu pago para conservar el lugar o prefieres que liberemos "
        f"el horario para otro consultante?"
    )
    encoded = urllib.parse.quote(msg)
    clean_phone = client_phone.replace("+", "").replace(" ", "").replace("-", "")
    if len(clean_phone) == 10:
        clean_phone = f"52{clean_phone}"
    return f"https://wa.me/{clean_phone}?text={encoded}"


def hydrate_booking_row(
    row: dict[str, Any],
    *,
    now: datetime | None = None,
    window_hours: int | None = None,
    package_info: str | None = None,
) -> BookingRead:
    ref_now = now or datetime.now(UTC)
    threshold = (
        window_hours if window_hours is not None else settings.payment_followup_threshold_hours
    )
    sched_dt = parse_iso_datetime(str(row["scheduled_at"]))
    hours_until = round((sched_dt - ref_now).total_seconds() / 3600.0, 2)

    b_status = str(row["booking_status"])
    p_arr = str(row["payment_arrangement"])
    p_status = str(row["payment_status"])

    needs_followup = p_status == "AWAITING_ACKNOWLEDGMENT" and (
        (b_status == "RESERVED" and hours_until <= threshold)
        or (p_arr == "DELAYED_ALLOWED" and b_status in ("RESERVED", "COMPLETED"))
    )

    service_name = str(row.get("service_name") or "")
    client_name = str(row.get("client_name") or "")
    client_phone = str(row.get("client_phone") or "")
    folio = str(row["booking_code"])
    amount_mxn = int(row["amount_mxn"])

    wa_client_url = build_whatsapp_link(
        service_name=service_name,
        scheduled_at=str(row["scheduled_at"]),
        folio=folio,
        amount_mxn=amount_mxn,
        package_info=package_info,
    )
    wa_followup_url = (
        build_assistant_followup_link(
            client_name=client_name,
            client_phone=client_phone,
            service_name=service_name,
            scheduled_at=str(row["scheduled_at"]),
            folio=folio,
            amount_mxn=amount_mxn,
        )
        if client_phone
        else None
    )

    return BookingRead(
        id=str(row["id"]),
        booking_code=folio,
        service_id=str(row["service_id"]),
        service_name=service_name or None,
        client_id=str(row["client_id"]),
        client_name=client_name or None,
        client_phone=client_phone or None,
        package_id=row.get("package_id"),
        scheduled_at=str(row["scheduled_at"]),
        duration_minutes=int(row.get("duration_minutes", 60)),
        buffer_minutes=int(row.get("buffer_minutes", 0)),
        booking_status=row["booking_status"],
        payment_arrangement=row["payment_arrangement"],
        payment_status=row["payment_status"],
        amount_mxn=amount_mxn,
        needs_payment_followup=needs_followup,
        hours_until_session=hours_until,
        exception_authorized_by=row.get("exception_authorized_by"),
        exception_authorized_at=row.get("exception_authorized_at"),
        exception_notes=row.get("exception_notes"),
        released_by=row.get("released_by"),
        released_at=row.get("released_at"),
        release_reason=row.get("release_reason"),
        acknowledged_by=row.get("acknowledged_by"),
        acknowledged_at=row.get("acknowledged_at"),
        gcal_event_id=row.get("gcal_event_id"),
        gcal_sync_status=row.get("gcal_sync_status", "NOT_CONFIGURED"),
        gcal_sync_error=row.get("gcal_sync_error"),
        gcal_synced_at=row.get("gcal_synced_at"),
        created_at=str(row["created_at"]),
        whatsapp_redirect_url=wa_client_url,
        whatsapp_followup_url=wa_followup_url,
    )


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
