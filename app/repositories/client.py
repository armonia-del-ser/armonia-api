from __future__ import annotations

import uuid
from typing import Any

import libsql_client

from app.db.database import result_to_dicts, row_to_dict
from app.schemas.client import Client360Read, ClientCreate, ClientRead, ClientUpdate
from app.schemas.package import PackageRead
from app.services.bookings import hydrate_booking_row
from app.services.timestamps import utc_now_iso


def _hydrate_client(row: dict[str, Any]) -> ClientRead:
    return ClientRead(
        id=str(row["id"]),
        full_name=str(row["full_name"]),
        phone_whatsapp=str(row["phone_whatsapp"]),
        email=row.get("email"),
        notes=row.get("notes"),
        created_at=str(row["created_at"]),
    )


def _hydrate_package(r: dict[str, Any]) -> PackageRead:
    total = int(r["total_sessions"])
    completed = int(r.get("completed_sessions", 0))
    return PackageRead(
        id=str(r["id"]),
        client_id=str(r["client_id"]),
        client_name=r.get("client_name"),
        client_phone=r.get("client_phone"),
        service_id=str(r["service_id"]),
        service_name=r.get("service_name"),
        total_sessions=total,
        completed_sessions=completed,
        remaining_sessions=max(0, total - completed),
        price_paid_mxn=int(r.get("price_paid_mxn", 0)),
        financial_status=r.get("financial_status", "PENDING"),
        notes=r.get("notes"),
        created_at=str(r["created_at"]),
        updated_at=str(r["updated_at"]),
    )


async def list_and_search_clients(
    client: libsql_client.Client,
    *,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ClientRead]:
    """
    List and search clients with optional case-insensitive matching on full_name and phone_whatsapp.
    Supports limit and offset pagination.
    """
    params: list[libsql_client.InValue] = []
    query = "SELECT id, full_name, phone_whatsapp, email, notes, created_at FROM clients"

    if search and search.strip():
        term = search.strip()
        query += " WHERE LOWER(full_name) LIKE ? OR phone_whatsapp LIKE ?"
        params.extend([f"%{term.lower()}%", f"%{term}%"])

    query += " ORDER BY full_name ASC LIMIT ? OFFSET ?;"
    params.extend([limit, offset])

    res = await client.execute(query, params)
    rows = result_to_dicts(res)
    return [_hydrate_client(r) for r in rows]


async def get_client_by_id(
    client: libsql_client.Client,
    client_id: str,
) -> ClientRead | None:
    """Retrieve client details by unique ID."""
    res = await client.execute(
        "SELECT id, full_name, phone_whatsapp, email, notes, created_at FROM clients WHERE id = ? LIMIT 1;",
        [client_id],
    )
    if not res.rows:
        return None
    return _hydrate_client(row_to_dict(res, res.rows[0]))


async def get_client_by_phone(
    client: libsql_client.Client,
    phone: str,
    *,
    exclude_id: str | None = None,
) -> ClientRead | None:
    """Find a client matching the given phone number, optionally excluding a specific client ID."""
    clean_phone = phone.strip()
    query = "SELECT id, full_name, phone_whatsapp, email, notes, created_at FROM clients WHERE phone_whatsapp = ?"
    params: list[libsql_client.InValue] = [clean_phone]
    if exclude_id:
        query += " AND id != ?"
        params.append(exclude_id)
    query += " LIMIT 1;"

    res = await client.execute(query, params)
    if not res.rows:
        return None
    return _hydrate_client(row_to_dict(res, res.rows[0]))


async def create_client(
    client: libsql_client.Client,
    payload: ClientCreate,
) -> ClientRead:
    """Persist a new client record."""
    client_id = str(uuid.uuid4())
    now = utc_now_iso()
    await client.execute(
        """
        INSERT INTO clients (id, full_name, phone_whatsapp, email, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        [
            client_id,
            payload.full_name.strip(),
            payload.phone_whatsapp.strip(),
            str(payload.email) if payload.email else None,
            payload.notes,
            now,
        ],
    )
    return ClientRead(
        id=client_id,
        full_name=payload.full_name.strip(),
        phone_whatsapp=payload.phone_whatsapp.strip(),
        email=payload.email,
        notes=payload.notes,
        created_at=now,
    )


async def update_client(
    client: libsql_client.Client,
    client_id: str,
    payload: ClientUpdate,
) -> ClientRead | None:
    """Update mutable client fields."""
    existing = await get_client_by_id(client, client_id)
    if not existing:
        return None

    updates: list[str] = []
    params: list[libsql_client.InValue] = []

    if payload.full_name is not None:
        updates.append("full_name = ?")
        params.append(payload.full_name.strip())
    if payload.phone_whatsapp is not None:
        updates.append("phone_whatsapp = ?")
        params.append(payload.phone_whatsapp.strip())
    if payload.email is not None:
        updates.append("email = ?")
        params.append(str(payload.email))
    if payload.notes is not None:
        updates.append("notes = ?")
        params.append(payload.notes)

    if not updates:
        return existing

    params.append(client_id)
    query = f"UPDATE clients SET {', '.join(updates)} WHERE id = ?;"
    await client.execute(query, params)
    return await get_client_by_id(client, client_id)


async def get_client_dependencies(
    client: libsql_client.Client,
    client_id: str,
) -> dict[str, int]:
    """Check how many bookings and packages reference this client."""
    b_res = await client.execute(
        "SELECT COUNT(*) FROM bookings WHERE client_id = ?;",
        [client_id],
    )
    bookings_count = int(str(b_res.rows[0][0] or 0)) if b_res.rows else 0

    p_res = await client.execute(
        "SELECT COUNT(*) FROM packages WHERE client_id = ?;",
        [client_id],
    )
    packages_count = int(str(p_res.rows[0][0] or 0)) if p_res.rows else 0

    return {
        "bookings_count": bookings_count,
        "packages_count": packages_count,
    }


async def delete_client(
    client: libsql_client.Client,
    client_id: str,
) -> None:
    """Delete client row from database."""
    await client.execute("DELETE FROM clients WHERE id = ?;", [client_id])


async def get_client_360_profile(
    client: libsql_client.Client,
    client_id: str,
) -> Client360Read | None:
    """
    Retrieve comprehensive 360-degree client profile containing contact info,
    active multi-session packages, and full booking history.
    """
    c_res = await client.execute(
        "SELECT id, full_name, phone_whatsapp, email, notes, created_at FROM clients WHERE id = ? LIMIT 1;",
        [client_id],
    )
    if not c_res.rows:
        return None
    c_dict = row_to_dict(c_res, c_res.rows[0])

    # Active packages (where completed_sessions < total_sessions)
    pkg_query = """
        SELECT p.*, c.full_name AS client_name, c.phone_whatsapp AS client_phone, s.name AS service_name
        FROM packages p
        JOIN clients c ON p.client_id = c.id
        JOIN services s ON p.service_id = s.id
        WHERE p.client_id = ? AND p.completed_sessions < p.total_sessions
        ORDER BY p.created_at DESC;
    """
    pkg_res = await client.execute(pkg_query, [client_id])
    active_packages = [_hydrate_package(r) for r in result_to_dicts(pkg_res)]

    # Recent booking history
    booking_query = """
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
        WHERE b.client_id = ?
        ORDER BY b.scheduled_at DESC;
    """
    b_res = await client.execute(booking_query, [client_id])
    bookings = [hydrate_booking_row(r) for r in result_to_dicts(b_res)]

    return Client360Read(
        id=str(c_dict["id"]),
        full_name=str(c_dict["full_name"]),
        phone_whatsapp=str(c_dict["phone_whatsapp"]),
        email=c_dict.get("email"),
        notes=c_dict.get("notes"),
        created_at=str(c_dict["created_at"]),
        active_packages=active_packages,
        booking_history=bookings,
        recent_bookings=bookings,
    )
