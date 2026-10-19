from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import record_admin_audit, require_admin
from app.db.database import get_db, result_to_dicts, row_to_dict
from app.schemas.auth import AdminPrincipal
from app.schemas.service import ServiceCreate, ServiceRead

router = APIRouter(prefix="/services", tags=["Services"])


@router.get("", response_model=list[ServiceRead])
async def list_services(active_only: bool = True):
    """Retrieve catalog of services offered by Armonía del Ser."""
    query = "SELECT * FROM services"
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY service_type ASC, name ASC;"

    async with get_db() as client:
        res = await client.execute(query)
        rows = result_to_dicts(res)
        for r in rows:
            r["is_active"] = bool(r.get("is_active", 1))
        return [ServiceRead(**r) for r in rows]


@router.get("/{service_id_or_slug}", response_model=ServiceRead)
async def get_service(service_id_or_slug: str):
    """Retrieve details for a specific service by ID or slug."""
    query = "SELECT * FROM services WHERE id = ? OR slug = ? LIMIT 1;"
    async with get_db() as client:
        res = await client.execute(query, [service_id_or_slug, service_id_or_slug])
        if not res.rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
        item = row_to_dict(res, res.rows[0])
        item["is_active"] = bool(item.get("is_active", 1))
        return ServiceRead(**item)


@router.post("", response_model=ServiceRead, status_code=status.HTTP_201_CREATED)
async def create_service(
    payload: ServiceCreate,
    admin: AdminPrincipal = Depends(require_admin),
):
    """Add a new service to the catalog (Admin action)."""
    service_id = str(uuid.uuid4())
    insert_query = """
        INSERT INTO services (
            id, slug, name, description, service_type, modality,
            default_schedule, price_mxn, max_capacity, duration_minutes, buffer_minutes, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """
    async with get_db() as client:
        try:
            await client.execute(
                insert_query,
                [
                    service_id,
                    payload.slug,
                    payload.name,
                    payload.description,
                    payload.service_type,
                    payload.modality,
                    payload.default_schedule,
                    payload.price_mxn,
                    payload.max_capacity,
                    payload.duration_minutes,
                    payload.buffer_minutes,
                    1 if payload.is_active else 0,
                ],
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to create service: {e}",
            ) from e

        await record_admin_audit(
            client,
            admin_email=admin.email,
            action_type="CREATE_SERVICE",
            entity_type="service",
            entity_id=service_id,
            details={"slug": payload.slug, "name": payload.name},
        )

        fetch_query = "SELECT * FROM services WHERE id = ? LIMIT 1;"
        res = await client.execute(fetch_query, [service_id])
        item = row_to_dict(res, res.rows[0])
        item["is_active"] = bool(item.get("is_active", 1))
        return ServiceRead(**item)
