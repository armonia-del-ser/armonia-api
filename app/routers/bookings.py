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


def generate_booking_code() -> str:
    """Generate a clean human-readable folio code, e.g. ADS-7F2A."""
    token = secrets.token_hex(2).upper()
    return f"ADS-{token}"


def build_whatsapp_link(service_name: str, scheduled_at: str, folio: str, amount_mxn: int) -> str:
    """Generate a pre-filled WhatsApp link instructing the client to send SPEI proof."""
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
    Creates a PENDING_PAYMENT booking and yields a pre-filled WhatsApp transfer message.
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

        # 2. Upsert client
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

        # 3. Create booking
        booking_id = str(uuid.uuid4())
        booking_code = generate_booking_code()
        now = datetime.now(UTC)
        expires_at = (now + timedelta(hours=2)).isoformat()
        amount_mxn = int(service["price_mxn"])

        insert_booking_query = """
            INSERT INTO bookings (
                id, booking_code, service_id, client_id, scheduled_at,
                status, amount_mxn, expires_at
            ) VALUES (?, ?, ?, ?, ?, 'PENDING_PAYMENT', ?, ?);
        """
        await client.execute(
            insert_booking_query,
            [
                booking_id,
                booking_code,
                service["id"],
                client_id,
                payload.scheduled_at,
                amount_mxn,
                expires_at,
            ],
        )

        wa_link = build_whatsapp_link(
            service_name=service["name"],
            scheduled_at=payload.scheduled_at,
            folio=booking_code,
            amount_mxn=amount_mxn,
        )

        return BookingRead(
            id=booking_id,
            booking_code=booking_code,
            service_id=service["id"],
            service_name=service["name"],
            client_id=str(client_id),
            client_name=payload.client_name,
            client_phone=payload.client_phone,
            scheduled_at=payload.scheduled_at,
            status="PENDING_PAYMENT",
            amount_mxn=amount_mxn,
            expires_at=expires_at,
            created_at=now.isoformat(),
            whatsapp_redirect_url=wa_link,
        )


@router.get("", response_model=list[BookingRead])
async def list_bookings(
    status_filter: BookingStatus | None = Query(None, alias="status"),
    limit: int = 50,
):
    """Admin-facing endpoint to list bookings, filtered by status."""
    query = """
        SELECT
            b.id, b.booking_code, b.service_id, s.name AS service_name,
            b.client_id, c.full_name AS client_name, c.phone_whatsapp AS client_phone,
            b.scheduled_at, b.status, b.amount_mxn, b.gcal_event_id,
            b.expires_at, b.created_at, b.confirmed_at
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        JOIN clients c ON b.client_id = c.id
    """
    params: list[libsql_client.InValue] = []
    if status_filter:
        query += " WHERE b.status = ?"
        params.append(status_filter)
    query += " ORDER BY b.scheduled_at DESC LIMIT ?;"
    params.append(limit)

    async with get_db() as client:
        res = await client.execute(query, params)
        rows = result_to_dicts(res)
        return [BookingRead(**r) for r in rows]
