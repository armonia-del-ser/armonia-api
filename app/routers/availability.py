from __future__ import annotations

from collections import defaultdict
from datetime import date, time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import settings
from app.db.database import get_db, result_to_dicts, row_to_dict
from app.routers.bookings import parse_iso_datetime
from app.schemas.availability import AvailabilityResponse, DayAvailabilityRead, SlotRead
from app.services.availability import (
    BlockedInterval,
    BusinessHours,
    blocked_interval,
    compute_available_slots,
)

router = APIRouter(prefix="/availability", tags=["Availability"])


def _parse_time(time_str: str) -> time:
    parts = [int(p) for p in time_str.split(":")]
    return time(hour=parts[0], minute=parts[1])


@router.get("", response_model=AvailabilityResponse)
async def get_availability(
    service_id: str = Query(..., description="ID of the service to check availability for"),
    date_from: date = Query(..., description="Start date (YYYY-MM-DD) inclusive"),
    date_to: date = Query(..., description="End date (YYYY-MM-DD) inclusive"),
):
    """
    Public-facing endpoint to query available appointment slots for INDIVIDUAL services.
    Enforces service duration and mandatory 15-minute post-session buffer collision rules.
    """
    if date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_to cannot be earlier than date_from.",
        )

    range_days = (date_to - date_from).days + 1
    if range_days > settings.availability_max_range_days:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Requested range ({range_days} days) exceeds maximum allowed limit ({settings.availability_max_range_days} days).",
        )

    async with get_db() as client:
        # 1. Fetch service details
        svc_res = await client.execute(
            "SELECT * FROM services WHERE id = ? AND is_active = 1 LIMIT 1;",
            [service_id],
        )
        if not svc_res.rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Service '{service_id}' not found or inactive.",
            )

        service = row_to_dict(svc_res, svc_res.rows[0])
        if service["service_type"] != "INDIVIDUAL":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Availability query is only applicable to INDIVIDUAL appointment services.",
            )

        duration_minutes = int(service.get("duration_minutes", 60))
        buffer_minutes = int(service.get("buffer_minutes", 15))
        service_name = str(service["name"])

        # 2. Fetch all existing active reservations that could cause collisions
        # (bookings where booking_status = 'RESERVED')
        b_res = await client.execute(
            """
            SELECT scheduled_at, duration_minutes, buffer_minutes
            FROM bookings
            WHERE booking_status = 'RESERVED';
            """
        )
        existing_rows = result_to_dicts(b_res)

        existing_intervals: list[BlockedInterval] = []
        for r in existing_rows:
            dt = parse_iso_datetime(str(r["scheduled_at"]))
            dur = int(r.get("duration_minutes", 60))
            buf = int(r.get("buffer_minutes", 0))
            existing_intervals.append(blocked_interval(dt, dur, buf))

    tz = ZoneInfo(settings.business_timezone)
    hours = BusinessHours(
        timezone=tz,
        open_time=_parse_time(settings.availability_open_time),
        close_time=_parse_time(settings.availability_close_time),
        working_weekdays=frozenset(settings.availability_working_weekdays),
        slot_step_minutes=settings.availability_slot_step_minutes,
    )

    available_slots = compute_available_slots(
        date_from=date_from,
        date_to=date_to,
        duration_minutes=duration_minutes,
        buffer_minutes=buffer_minutes,
        existing=existing_intervals,
        hours=hours,
    )

    # Group available slots by date
    days_dict: dict[date, list[SlotRead]] = defaultdict(list)
    for slot in available_slots:
        slot_date = slot.start.date()
        days_dict[slot_date].append(
            SlotRead(start=slot.start.isoformat(), end=slot.end.isoformat())
        )

    # Maintain sorted dates representation
    days_list: list[DayAvailabilityRead] = [
        DayAvailabilityRead(date=d.isoformat(), slots=slots)
        for d, slots in sorted(days_dict.items(), key=lambda x: x[0])
    ]

    return AvailabilityResponse(
        service_id=service_id,
        service_name=service_name,
        duration_minutes=duration_minutes,
        buffer_minutes=buffer_minutes,
        timezone=settings.business_timezone,
        days=days_list,
    )
