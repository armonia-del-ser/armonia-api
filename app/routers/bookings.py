from __future__ import annotations

import secrets
import urllib.parse
import uuid
from datetime import UTC, datetime, timedelta

import libsql_client
from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import settings
from app.db.database import get_db, result_to_dicts, row_to_dict
from app.schemas.booking import BookingCreate, BookingRead, BookingStatus

router = APIRouter(prefix="/bookings", tags=["Bookings"])


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
    existing_bookings: list[dict],
) -> bool:
    """
    Returns True if the requested slot interval (including mandatory buffer)
    collides with any existing active booking interval (including its buffer).
    Formula: max(A_start, B_start) < min(A_blocked_end, B_blocked_end)
    """
    new_blocked_end = new_start + timedelta(minutes=new_duration + new_buffer)
    for b in existing_bookings:
        exist_start = parse_iso_datetime(str(b["scheduled_at"]))
        exist_duration = int(b.get("duration_minutes", 60))
        exist_buffer = int(b.get("buffer_minutes", 0))
        exist_blocked_end = exist_start + timedelta(minutes=exist_duration + exist_buffer)

        # Overlap exists if start of each is before blocked end of other
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
    """Generate a pre-filled WhatsApp link instructing the client or reporting booking."""
    if package_info:
        msg = (
            f"Hola Jazmín! ✨ Agendé mi sesión ({package_info}) para *{service_name}* "
            f"para el {scheduled_at}.\n\n"
            f"📌 *Folio de cita:* {folio}\n"
            f"¡Nos vemos pronto!"
        )
    else:
        msg = (
            f"Hola Jazmín! ✨ Acabo de apartar mi lugar para *{service_name}* "
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


@router.post("", response_model=BookingRead, status_code=status.HTTP_201_CREATED)
async def create_booking(payload: BookingCreate):
    """
    Client-facing or self-service reservation endpoint.
    Creates a PENDING_PAYMENT booking (or CONFIRMED if redeeming a prepaid package),
    enforcing mandatory buffer times between individual therapy consultations.
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

        # 2. Collision & Buffer Check for ONE_ON_ONE services
        new_start = parse_iso_datetime(payload.scheduled_at)
        if service["service_type"] == "ONE_ON_ONE":
            active_res = await client.execute(
                """
                SELECT b.scheduled_at, b.duration_minutes, b.buffer_minutes
                FROM bookings b
                JOIN services s ON b.service_id = s.id
                WHERE b.status IN ('PENDING_PAYMENT', 'CONFIRMED') AND s.service_type = 'ONE_ON_ONE';
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

        # 3. Upsert client
        client_res = await client.execute(
            "SELECT id FROM clients WHERE phone_whatsapp = ? LIMIT 1;",
            [payload.client_phone],
        )
        if client_res.rows:
            client_id = client_res.rows[0][0]
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

        # 4. Handle Package Redemption vs New Payment
        now = datetime.now(UTC)
        package_info: str | None = None
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

            # Increment package sessions
            await client.execute(
                "UPDATE packages SET completed_sessions = completed_sessions + 1, updated_at = ? WHERE id = ?;",
                [now.isoformat(), payload.package_id],
            )
            booking_status: BookingStatus = "CONFIRMED"
            amount_mxn = 0
            confirmed_at: str | None = now.isoformat()
            package_info = f"Sesión {completed + 1} de {total}"
        else:
            booking_status = "PENDING_PAYMENT"
            amount_mxn = int(service["price_mxn"])
            confirmed_at = None

        booking_id = str(uuid.uuid4())
        booking_code = generate_booking_code()
        expires_at = (now + timedelta(hours=2)).isoformat()

        insert_booking_query = """
            INSERT INTO bookings (
                id, booking_code, service_id, client_id, package_id, scheduled_at,
                duration_minutes, buffer_minutes, status, amount_mxn, expires_at, created_at, confirmed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
                amount_mxn,
                expires_at,
                now.isoformat(),
                confirmed_at,
            ],
        )

        wa_link = build_whatsapp_link(
            service_name=service["name"],
            scheduled_at=payload.scheduled_at,
            folio=booking_code,
            amount_mxn=amount_mxn,
            package_info=package_info,
        )

        return BookingRead(
            id=booking_id,
            booking_code=booking_code,
            service_id=service["id"],
            service_name=service["name"],
            client_id=str(client_id),
            client_name=payload.client_name,
            client_phone=payload.client_phone,
            package_id=payload.package_id,
            scheduled_at=payload.scheduled_at,
            duration_minutes=duration_minutes,
            buffer_minutes=buffer_minutes,
            status=booking_status,
            amount_mxn=amount_mxn,
            expires_at=expires_at,
            created_at=now.isoformat(),
            confirmed_at=confirmed_at,
            whatsapp_redirect_url=wa_link,
        )


@router.get("", response_model=list[BookingRead])
async def list_bookings(
    status_filter: BookingStatus | None = Query(None, alias="status"),
    client_id: str | None = None,
    limit: int = 50,
):
    """Admin-facing endpoint to list bookings, filtered by status or client."""
    query = """
        SELECT
            b.id, b.booking_code, b.service_id, s.name AS service_name,
            b.client_id, c.full_name AS client_name, c.phone_whatsapp AS client_phone,
            b.package_id, b.scheduled_at, b.duration_minutes, b.buffer_minutes,
            b.status, b.amount_mxn, b.gcal_event_id, b.expires_at, b.created_at, b.confirmed_at
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        JOIN clients c ON b.client_id = c.id
    """
    params: list[libsql_client.InValue] = []
    clauses: list[str] = []

    if status_filter:
        clauses.append("b.status = ?")
        params.append(status_filter)
    if client_id:
        clauses.append("b.client_id = ?")
        params.append(client_id)

    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    query += " ORDER BY b.scheduled_at DESC LIMIT ?;"
    params.append(limit)

    async with get_db() as client:
        res = await client.execute(query, params)
        rows = result_to_dicts(res)
        return [BookingRead(**r) for r in rows]
