from __future__ import annotations

import uuid
from datetime import UTC, datetime

import libsql_client
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import record_admin_audit, require_admin
from app.db.database import get_db, result_to_dicts, row_to_dict
from app.schemas.auth import AdminPrincipal
from app.schemas.package import FinancialStatus, PackageCreate, PackageRead, PackageUpdate

router = APIRouter(prefix="/packages", tags=["Packages"])


def _hydrate_package(r: dict) -> PackageRead:
    total = int(r["total_sessions"])
    completed = int(r.get("completed_sessions", 0))
    return PackageRead(
        id=r["id"],
        client_id=r["client_id"],
        client_name=r.get("client_name"),
        client_phone=r.get("client_phone"),
        service_id=r["service_id"],
        service_name=r.get("service_name"),
        total_sessions=total,
        completed_sessions=completed,
        remaining_sessions=max(0, total - completed),
        price_paid_mxn=int(r.get("price_paid_mxn", 0)),
        financial_status=r.get("financial_status", "PENDING"),
        notes=r.get("notes"),
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


@router.post("", response_model=PackageRead, status_code=status.HTTP_201_CREATED)
async def create_package(
    payload: PackageCreate,
    admin: AdminPrincipal = Depends(require_admin),
):
    """
    Create a multi-session therapy package for a client (e.g. 5 or 10 sessions).
    Allows tracking remaining credits and financial status.
    """
    async with get_db() as client:
        c_res = await client.execute(
            "SELECT id FROM clients WHERE id = ? LIMIT 1;", [payload.client_id]
        )
        if not c_res.rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

        s_res = await client.execute(
            "SELECT id FROM services WHERE id = ? LIMIT 1;", [payload.service_id]
        )
        if not s_res.rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")

        package_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()

        insert_query = """
            INSERT INTO packages (
                id, client_id, service_id, total_sessions, completed_sessions,
                price_paid_mxn, financial_status, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        await client.execute(
            insert_query,
            [
                package_id,
                payload.client_id,
                payload.service_id,
                payload.total_sessions,
                payload.completed_sessions,
                payload.price_paid_mxn,
                payload.financial_status,
                payload.notes,
                now,
                now,
            ],
        )

        await record_admin_audit(
            client,
            admin_email=admin.email,
            action_type="CREATE_PACKAGE",
            entity_type="package",
            entity_id=package_id,
            details={
                "client_id": payload.client_id,
                "total_sessions": payload.total_sessions,
                "financial_status": payload.financial_status,
            },
        )

        fetch_query = """
            SELECT p.*, c.full_name AS client_name, c.phone_whatsapp AS client_phone, s.name AS service_name
            FROM packages p
            JOIN clients c ON p.client_id = c.id
            JOIN services s ON p.service_id = s.id
            WHERE p.id = ? LIMIT 1;
        """
        res = await client.execute(fetch_query, [package_id])
        return _hydrate_package(row_to_dict(res, res.rows[0]))


@router.get("", response_model=list[PackageRead])
async def list_packages(
    client_id: str | None = None,
    financial_status: FinancialStatus | None = Query(None, alias="status"),
    _admin: AdminPrincipal = Depends(require_admin),
):
    """List therapy packages with filter by client or financial status."""
    query = """
        SELECT p.*, c.full_name AS client_name, c.phone_whatsapp AS client_phone, s.name AS service_name
        FROM packages p
        JOIN clients c ON p.client_id = c.id
        JOIN services s ON p.service_id = s.id
    """
    params: list[libsql_client.InValue] = []
    clauses: list[str] = []

    if client_id:
        clauses.append("p.client_id = ?")
        params.append(client_id)
    if financial_status:
        clauses.append("p.financial_status = ?")
        params.append(financial_status)

    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY p.created_at DESC;"

    async with get_db() as client:
        res = await client.execute(query, params)
        rows = result_to_dicts(res)
        return [_hydrate_package(r) for r in rows]


@router.get("/{package_id}", response_model=PackageRead)
async def get_package(
    package_id: str,
    _admin: AdminPrincipal = Depends(require_admin),
):
    """Retrieve details and remaining balance for a specific package."""
    query = """
        SELECT p.*, c.full_name AS client_name, c.phone_whatsapp AS client_phone, s.name AS service_name
        FROM packages p
        JOIN clients c ON p.client_id = c.id
        JOIN services s ON p.service_id = s.id
        WHERE p.id = ? LIMIT 1;
    """
    async with get_db() as client:
        res = await client.execute(query, [package_id])
        if not res.rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")
        return _hydrate_package(row_to_dict(res, res.rows[0]))


@router.patch("/{package_id}", response_model=PackageRead)
async def update_package(
    package_id: str,
    payload: PackageUpdate,
    admin: AdminPrincipal = Depends(require_admin),
):
    """Update package notes, sessions count, or financial status."""
    now = datetime.now(UTC).isoformat()
    async with get_db() as client:
        res = await client.execute("SELECT * FROM packages WHERE id = ? LIMIT 1;", [package_id])
        if not res.rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")

        updates: list[str] = ["updated_at = ?"]
        params: list[libsql_client.InValue] = [now]

        if payload.total_sessions is not None:
            updates.append("total_sessions = ?")
            params.append(payload.total_sessions)
        if payload.completed_sessions is not None:
            updates.append("completed_sessions = ?")
            params.append(payload.completed_sessions)
        if payload.price_paid_mxn is not None:
            updates.append("price_paid_mxn = ?")
            params.append(payload.price_paid_mxn)
        if payload.financial_status is not None:
            updates.append("financial_status = ?")
            params.append(payload.financial_status)
        if payload.notes is not None:
            updates.append("notes = ?")
            params.append(payload.notes)

        params.append(package_id)
        update_query = f"UPDATE packages SET {', '.join(updates)} WHERE id = ?;"
        await client.execute(update_query, params)

        await record_admin_audit(
            client,
            admin_email=admin.email,
            action_type="UPDATE_PACKAGE",
            entity_type="package",
            entity_id=package_id,
            details=payload.model_dump(exclude_none=True),
        )

        fetch_query = """
            SELECT p.*, c.full_name AS client_name, c.phone_whatsapp AS client_phone, s.name AS service_name
            FROM packages p
            JOIN clients c ON p.client_id = c.id
            JOIN services s ON p.service_id = s.id
            WHERE p.id = ? LIMIT 1;
        """
        updated_res = await client.execute(fetch_query, [package_id])
        return _hydrate_package(row_to_dict(updated_res, updated_res.rows[0]))
