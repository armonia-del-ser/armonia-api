from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import record_admin_audit, require_admin
from app.core.config import settings
from app.db.database import get_db, result_to_dicts, row_to_dict
from app.models.payment import PaymentMethodEnum
from app.routers.bookings import (
    BOOKING_SELECT_QUERY,
    generate_booking_code,
    parse_iso_datetime,
)
from app.schemas.auth import AdminPrincipal
from app.schemas.roster import (
    QuickCheckinRequest,
    QuickCheckinResponse,
    RosterAttendeeRead,
    RosterSessionRead,
)
from app.services.calendar import calendar_service

router = APIRouter(prefix="/rosters", tags=["Group Workshop Rosters"])


def _to_utc_instant_key(dt_str: str) -> str:
    """Normalize ISO datetime string to an ISO UTC string so different representations group together."""
    dt = parse_iso_datetime(dt_str)
    return dt.astimezone(UTC).isoformat()


@router.get("", response_model=list[RosterSessionRead])
async def get_rosters(
    date_from: date = Query(..., description="Start date (YYYY-MM-DD)"),
    date_to: date = Query(..., description="End date (YYYY-MM-DD)"),
    service_id: str | None = Query(None, description="Optional service ID filter"),
    _admin: AdminPrincipal = Depends(require_admin),
):
    """
    Query workshop roster sessions for GROUP services within [date_from, date_to].
    Groups bookings by session instant across different ISO timezone representations.
    Excludes RELEASED and CANCELLED bookings.
    """
    if date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_to cannot be earlier than date_from.",
        )

    # Convert date range to Mexico City timezone boundaries
    tz = ZoneInfo(settings.business_timezone)
    start_dt = datetime(
        date_from.year, date_from.month, date_from.day, 0, 0, 0, tzinfo=tz
    ).astimezone(UTC)
    end_dt = datetime(
        date_to.year, date_to.month, date_to.day, 23, 59, 59, 999999, tzinfo=tz
    ).astimezone(UTC)

    query = (
        BOOKING_SELECT_QUERY
        + """
        WHERE s.service_type = 'GROUP'
          AND b.booking_status IN ('RESERVED', 'COMPLETED', 'NO_SHOW')
          AND s.is_active = 1
        """
    )
    params = []
    if service_id:
        query += " AND s.id = ?"
        params.append(service_id)

    query += " ORDER BY b.scheduled_at ASC;"

    async with get_db() as client:
        # Also fetch group service details
        svc_query = "SELECT id, name, max_capacity FROM services WHERE service_type = 'GROUP';"
        svc_res = await client.execute(svc_query)
        services_by_id = {
            str(r[0]): {"name": str(r[1]), "max_capacity": int(str(r[2] or 1))}
            for r in svc_res.rows
        }

        res = await client.execute(query, params)
        rows = result_to_dicts(res)

    # Group by (service_id, normalized_instant_key)
    sessions_map: dict[tuple[str, str], dict] = {}

    for r in rows:
        sched_dt_utc = parse_iso_datetime(str(r["scheduled_at"])).astimezone(UTC)
        if not (start_dt <= sched_dt_utc <= end_dt):
            continue

        svc_id = str(r["service_id"])
        instant_key = sched_dt_utc.isoformat()
        group_key = (svc_id, instant_key)

        if group_key not in sessions_map:
            svc_info = services_by_id.get(
                svc_id, {"name": str(r.get("service_name", "")), "max_capacity": 20}
            )
            sessions_map[group_key] = {
                "service_id": svc_id,
                "service_name": svc_info["name"],
                "scheduled_at": str(r["scheduled_at"]),  # preserve representative representation
                "max_capacity": svc_info["max_capacity"],
                "attendees": [],
            }

        booking_status = str(r["booking_status"])
        attended = booking_status == "COMPLETED"

        sessions_map[group_key]["attendees"].append(
            RosterAttendeeRead(
                booking_id=str(r["id"]),
                booking_code=str(r["booking_code"]),
                client_id=str(r["client_id"]),
                client_name=str(r.get("client_name") or ""),
                client_phone=str(r.get("client_phone") or ""),
                client_email=r.get("client_email"),
                booking_status=booking_status,
                payment_arrangement=str(r["payment_arrangement"]),
                payment_status=str(r["payment_status"]),
                amount_mxn=int(r["amount_mxn"]),
                attended=attended,
            )
        )

    roster_sessions: list[RosterSessionRead] = []
    for s_data in sessions_map.values():
        attendees = s_data["attendees"]
        occupied_count = len(attendees)
        attended_count = sum(1 for a in attendees if a.attended)
        roster_sessions.append(
            RosterSessionRead(
                service_id=s_data["service_id"],
                service_name=s_data["service_name"],
                scheduled_at=s_data["scheduled_at"],
                max_capacity=s_data["max_capacity"],
                occupied_count=occupied_count,
                attended_count=attended_count,
                attendees=attendees,
            )
        )

    return roster_sessions


@router.post("/quick-checkin", response_model=QuickCheckinResponse)
async def quick_checkin(
    payload: QuickCheckinRequest,
    admin: AdminPrincipal = Depends(require_admin),
):
    """
    Perform a quick check-in for group workshops:
    - Mode 1: Check in an existing booking (marking COMPLETED, optionally recording CASH payment).
    - Mode 2: Register a walk-in attendee directly into COMPLETED status.
    """
    now = datetime.now(UTC).isoformat()

    async with get_db() as client:
        # MODE 1: Existing booking check-in
        if payload.booking_id:
            b_res = await client.execute(
                BOOKING_SELECT_QUERY + " WHERE b.id = ? LIMIT 1;",
                [payload.booking_id],
            )
            if not b_res.rows:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found."
                )

            booking = row_to_dict(b_res, b_res.rows[0])
            svc_res = await client.execute(
                "SELECT service_type FROM services WHERE id = ?;", [booking["service_id"]]
            )
            if not svc_res.rows or str(svc_res.rows[0][0]) != "GROUP":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Quick check-in is only available for GROUP workshops.",
                )

            current_status = str(booking["booking_status"])
            if current_status in ("RELEASED", "CANCELLED"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot check in a {current_status.lower()} booking.",
                )
            if current_status == "COMPLETED":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This attendee has already checked in.",
                )

            new_booking_status = "COMPLETED"
            payment_id: str | None = None
            current_p_status = str(booking["payment_status"])
            current_p_arr = str(booking["payment_arrangement"])

            if payload.paid_cash:
                new_p_status = "ACKNOWLEDGED"
                new_p_arr = current_p_arr
                payment_id = str(uuid.uuid4())
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
                        booking["id"],
                        booking["amount_mxn"],
                        PaymentMethodEnum.CASH.value,
                        admin.email,
                        now,
                        payload.notes or "Quick check-in cash payment",
                        now,
                    ],
                )
            else:
                if current_p_status == "ACKNOWLEDGED":
                    new_p_status = "ACKNOWLEDGED"
                    new_p_arr = current_p_arr
                else:
                    new_p_status = "AWAITING_ACKNOWLEDGMENT"
                    new_p_arr = "DELAYED_ALLOWED"

            cal_res = await calendar_service.sync_booking_event(
                booking_id=str(booking["id"]),
                booking_code=str(booking["booking_code"]),
                service_name=str(booking["service_name"]),
                client_name=str(booking["client_name"]),
                scheduled_at=str(booking["scheduled_at"]),
                duration_minutes=int(booking["duration_minutes"]),
                booking_status=new_booking_status,
                payment_arrangement=new_p_arr,
                payment_status=new_p_status,
                existing_event_id=booking.get("gcal_event_id"),
            )

            await client.execute(
                """
                UPDATE bookings
                SET booking_status = ?,
                    payment_arrangement = ?,
                    payment_status = ?,
                    gcal_event_id = ?,
                    gcal_sync_status = ?,
                    gcal_sync_error = ?,
                    gcal_synced_at = ?
                WHERE id = ?;
                """,
                [
                    new_booking_status,
                    new_p_arr,
                    new_p_status,
                    cal_res.event_id,
                    cal_res.sync_status,
                    cal_res.sync_error,
                    cal_res.synced_at,
                    booking["id"],
                ],
            )

            await record_admin_audit(
                client,
                admin_email=admin.email,
                action_type="ROSTER_CHECKIN",
                entity_type="booking",
                entity_id=str(booking["id"]),
                details={"paid_cash": payload.paid_cash, "payment_id": payment_id},
            )

            attendee = RosterAttendeeRead(
                booking_id=str(booking["id"]),
                booking_code=str(booking["booking_code"]),
                client_id=str(booking["client_id"]),
                client_name=str(booking["client_name"]),
                client_phone=str(booking["client_phone"]),
                client_email=booking.get("client_email"),
                booking_status=new_booking_status,
                payment_arrangement=new_p_arr,
                payment_status=new_p_status,
                amount_mxn=int(booking["amount_mxn"]),
                attended=True,
            )
            return QuickCheckinResponse(walk_in=False, attendee=attendee, payment_id=payment_id)

        # MODE 2: Walk-in registration and check-in
        service_id = str(payload.service_id)
        scheduled_at = str(payload.scheduled_at)
        client_name = str(payload.client_name)
        client_phone = str(payload.client_phone)

        svc_res = await client.execute(
            "SELECT * FROM services WHERE id = ? AND is_active = 1 LIMIT 1;",
            [service_id],
        )
        if not svc_res.rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Service not found or inactive."
            )

        service = row_to_dict(svc_res, svc_res.rows[0])
        if service["service_type"] != "GROUP":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Walk-in check-in is only applicable to GROUP workshops.",
            )

        # Capacity check for this group workshop session
        cap_res = await client.execute(
            """
            SELECT COUNT(*) AS count
            FROM bookings
            WHERE service_id = ? AND scheduled_at = ? AND booking_status IN ('RESERVED', 'COMPLETED');
            """,
            [service_id, scheduled_at],
        )
        current_count = int(str(cap_res.rows[0][0] or 0))
        max_cap = int(service.get("max_capacity", 1))
        if current_count >= max_cap:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El taller ha alcanzado su cupo máximo ({max_cap}) para esta sesión.",
            )

        # Upsert client by phone
        c_res = await client.execute(
            "SELECT id FROM clients WHERE phone_whatsapp = ? LIMIT 1;",
            [client_phone],
        )
        if c_res.rows:
            client_id = str(c_res.rows[0][0])
        else:
            client_id = str(uuid.uuid4())
            await client.execute(
                "INSERT INTO clients (id, full_name, phone_whatsapp, email, notes) VALUES (?, ?, ?, ?, ?);",
                [client_id, client_name, client_phone, payload.client_email, "Walk-in attendee"],
            )

        booking_id = str(uuid.uuid4())
        booking_code = generate_booking_code()
        duration_minutes = int(service.get("duration_minutes", 60))
        buffer_minutes = int(service.get("buffer_minutes", 0))
        amount_mxn = int(service["price_mxn"])

        booking_status = "COMPLETED"
        if payload.paid_cash:
            payment_status = "ACKNOWLEDGED"
            payment_arrangement = "PREPAID_DEFAULT"
        else:
            payment_status = "AWAITING_ACKNOWLEDGMENT"
            payment_arrangement = "DELAYED_ALLOWED"

        cal_res = await calendar_service.sync_booking_event(
            booking_id=booking_id,
            booking_code=booking_code,
            service_name=str(service["name"]),
            client_name=client_name,
            scheduled_at=scheduled_at,
            duration_minutes=duration_minutes,
            booking_status=booking_status,
            payment_arrangement=payment_arrangement,
            payment_status=payment_status,
        )

        await client.execute(
            """
            INSERT INTO bookings (
                id, booking_code, service_id, client_id, scheduled_at,
                duration_minutes, buffer_minutes, booking_status, payment_arrangement,
                payment_status, amount_mxn, gcal_event_id, gcal_sync_status,
                gcal_sync_error, gcal_synced_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            [
                booking_id,
                booking_code,
                service["id"],
                client_id,
                scheduled_at,
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
                now,
            ],
        )

        payment_id = None
        if payload.paid_cash:
            payment_id = str(uuid.uuid4())
            await client.execute(
                """
                INSERT INTO payments (
                    id, booking_id, amount_mxn, payment_method, status,
                    acknowledged_by, acknowledged_at, notes, created_at
                ) VALUES (?, ?, ?, ?, 'ACKNOWLEDGED', ?, ?, ?, ?);
                """,
                [
                    payment_id,
                    booking_id,
                    amount_mxn,
                    PaymentMethodEnum.CASH.value,
                    admin.email,
                    now,
                    payload.notes or "Walk-in cash payment",
                    now,
                ],
            )

        await record_admin_audit(
            client,
            admin_email=admin.email,
            action_type="ROSTER_WALK_IN",
            entity_type="booking",
            entity_id=booking_id,
            details={"paid_cash": payload.paid_cash, "payment_id": payment_id},
        )

        attendee = RosterAttendeeRead(
            booking_id=booking_id,
            booking_code=booking_code,
            client_id=client_id,
            client_name=client_name,
            client_phone=client_phone,
            client_email=payload.client_email,
            booking_status=booking_status,
            payment_arrangement=payment_arrangement,
            payment_status=payment_status,
            amount_mxn=amount_mxn,
            attended=True,
        )

        return QuickCheckinResponse(walk_in=True, attendee=attendee, payment_id=payment_id)
