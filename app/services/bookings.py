from __future__ import annotations

import secrets
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import settings
from app.schemas.booking import BookingRead
from app.services.timestamps import parse_iso_datetime


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


def calculate_hours_until(scheduled_at: datetime | str, now: datetime | None = None) -> float:
    """Calculate hours remaining until scheduled_at from now (UTC)."""
    ref_now = now or datetime.now(UTC)
    if isinstance(scheduled_at, str):
        sched_dt = parse_iso_datetime(scheduled_at)
    else:
        sched_dt = (
            scheduled_at if scheduled_at.tzinfo is not None else scheduled_at.replace(tzinfo=UTC)
        )
    return round((sched_dt - ref_now).total_seconds() / 3600.0, 2)


def evaluate_payment_followup(
    *,
    booking_status: str,
    payment_status: str,
    payment_arrangement: str,
    hours_until: float,
    threshold_hours: int = 48,
) -> bool:
    """
    Evaluate if an appointment requires payment follow-up:
    1. payment_status must be 'AWAITING_ACKNOWLEDGMENT'
    2. AND either:
       a) booking_status is 'RESERVED' and hours_until <= threshold_hours (default 48h)
       b) payment_arrangement is 'DELAYED_ALLOWED' and booking_status is 'RESERVED' or 'COMPLETED'
    """
    if payment_status != "AWAITING_ACKNOWLEDGMENT":
        return False

    is_imminent_reserved = (booking_status == "RESERVED") and (hours_until <= threshold_hours)
    is_delayed_allowed_active = (payment_arrangement == "DELAYED_ALLOWED") and (
        booking_status in ("RESERVED", "COMPLETED")
    )

    return is_imminent_reserved or is_delayed_allowed_active


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
    hours_until = calculate_hours_until(str(row["scheduled_at"]), ref_now)
    needs_followup = evaluate_payment_followup(
        booking_status=str(row["booking_status"]),
        payment_status=str(row["payment_status"]),
        payment_arrangement=str(row["payment_arrangement"]),
        hours_until=hours_until,
        threshold_hours=threshold,
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
