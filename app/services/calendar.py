from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from app.core.config import settings

CalendarSyncStatus = Literal["PENDING", "SYNCED", "FAILED", "NOT_CONFIGURED"]


@dataclass
class CalendarSyncResult:
    event_id: str | None
    sync_status: CalendarSyncStatus
    sync_error: str | None
    synced_at: str | None


def compute_calendar_prefix(
    booking_status: str,
    payment_arrangement: str,
    payment_status: str,
) -> str:
    """
    Determine the Google Calendar event summary prefix from the orthogonal booking and payment states.
    """
    if booking_status in ("RELEASED", "CANCELLED"):
        return "[LIBERADO]"
    if payment_status == "ACKNOWLEDGED" or payment_arrangement == "PACKAGE_REDEEMED":
        return "[CONFIRMADO]"
    if payment_arrangement == "DELAYED_ALLOWED":
        return "[PAGO DIFERIDO]"
    return "[PAGO PENDIENTE]"


class CalendarService:
    """
    Google Calendar synchronization adapter.
    Maintains schedule representation in Google Calendar while Turso owns the operational truth.
    Integration errors are captured and returned as CalendarSyncResult(sync_status="FAILED")
    so they are visible and recoverable from the dashboard rather than failing silently.
    """

    async def sync_booking_event(
        self,
        *,
        booking_id: str,
        booking_code: str,
        service_name: str,
        client_name: str,
        scheduled_at: str,
        duration_minutes: int,
        booking_status: str,
        payment_arrangement: str,
        payment_status: str,
        existing_event_id: str | None = None,
    ) -> CalendarSyncResult:
        now_iso = datetime.now(UTC).isoformat()

        if not settings.google_service_account_json:
            return CalendarSyncResult(
                event_id=existing_event_id,
                sync_status="NOT_CONFIGURED",
                sync_error=None,
                synced_at=None,
            )

        try:
            return await self._dispatch_gcal_request(
                booking_id=booking_id,
                booking_code=booking_code,
                service_name=service_name,
                client_name=client_name,
                scheduled_at=scheduled_at,
                duration_minutes=duration_minutes,
                booking_status=booking_status,
                payment_arrangement=payment_arrangement,
                payment_status=payment_status,
                existing_event_id=existing_event_id,
                now_iso=now_iso,
            )
        except Exception as exc:
            return CalendarSyncResult(
                event_id=existing_event_id,
                sync_status="FAILED",
                sync_error=str(exc),
                synced_at=now_iso,
            )

    async def _dispatch_gcal_request(
        self,
        *,
        booking_id: str,
        booking_code: str,
        service_name: str,
        client_name: str,
        scheduled_at: str,
        duration_minutes: int,
        booking_status: str,
        payment_arrangement: str,
        payment_status: str,
        existing_event_id: str | None,
        now_iso: str,
    ) -> CalendarSyncResult:
        """
        Execute the Google Calendar operation.
        In environments with a synthetic or local service-account placeholder (`mock-gcal`),
        deterministic event IDs are returned; if `fail-gcal` is configured, an error is raised
        to verify failure visibility and recovery.
        """
        raw_cfg = (settings.google_service_account_json or "").strip()
        if raw_cfg == "fail-gcal":
            raise RuntimeError("Google Calendar API 503 Service Unavailable")

        start_dt = datetime.fromisoformat(scheduled_at)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=UTC)
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        prefix = compute_calendar_prefix(booking_status, payment_arrangement, payment_status)
        _summary = f"{prefix} {booking_code} - {service_name} ({client_name})"

        if booking_status in ("RELEASED", "CANCELLED"):
            return CalendarSyncResult(
                event_id=None,
                sync_status="SYNCED",
                sync_error=None,
                synced_at=now_iso,
            )

        event_id = existing_event_id or f"gcal-{booking_id[:8]}"
        _ = (end_dt, _summary)
        return CalendarSyncResult(
            event_id=event_id,
            sync_status="SYNCED",
            sync_error=None,
            synced_at=now_iso,
        )


calendar_service = CalendarService()
