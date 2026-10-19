from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import record_admin_audit, require_admin
from app.db.database import get_db
from app.repositories import client as client_repo
from app.schemas.auth import AdminPrincipal
from app.schemas.client import Client360Read, ClientCreate, ClientRead, ClientUpdate

router = APIRouter(prefix="/clients", tags=["Clients"])


@router.get("", response_model=list[ClientRead])
async def list_clients(
    search: str | None = Query(
        default=None, description="Case-insensitive search query matching name or phone"
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _admin: AdminPrincipal = Depends(require_admin),
):
    """
    Search and list clients with autocomplete support matching full_name or phone_whatsapp.
    Supports limit and offset pagination.
    """
    async with get_db() as db:
        return await client_repo.list_and_search_clients(
            db, search=search, limit=limit, offset=offset
        )


@router.get("/{client_id}", response_model=Client360Read)
async def get_client(
    client_id: str,
    _admin: AdminPrincipal = Depends(require_admin),
):
    """
    Client 360 profile returning contact information, operational notes,
    active multi-session packages (completed vs total sessions), and recent booking history.
    """
    async with get_db() as db:
        profile = await client_repo.get_client_360_profile(db, client_id)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Client not found",
            )
        return profile


@router.post("", response_model=ClientRead, status_code=status.HTTP_201_CREATED)
async def create_client(
    payload: ClientCreate,
    admin: AdminPrincipal = Depends(require_admin),
):
    """
    Explicitly register a new client with phone number validation and duplicate detection.
    """
    async with get_db() as db:
        existing = await client_repo.get_client_by_phone(db, payload.phone_whatsapp)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A client with phone {payload.phone_whatsapp} already exists.",
            )

        new_client = await client_repo.create_client(db, payload)

        await record_admin_audit(
            db,
            admin_email=admin.email,
            action_type="CREATE_CLIENT",
            entity_type="client",
            entity_id=new_client.id,
            details={
                "full_name": new_client.full_name,
                "phone_whatsapp": new_client.phone_whatsapp,
            },
        )
        return new_client


@router.patch("/{client_id}", response_model=ClientRead)
async def update_client(
    client_id: str,
    payload: ClientUpdate,
    admin: AdminPrincipal = Depends(require_admin),
):
    """
    Update client contact details, full_name, phone_whatsapp, email, or clinical/operational notes.
    """
    async with get_db() as db:
        existing = await client_repo.get_client_by_id(db, client_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Client not found",
            )

        if payload.phone_whatsapp:
            dup = await client_repo.get_client_by_phone(
                db, payload.phone_whatsapp, exclude_id=client_id
            )
            if dup:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Another client with phone {payload.phone_whatsapp} already exists.",
                )

        updated = await client_repo.update_client(db, client_id, payload)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Client not found",
            )

        await record_admin_audit(
            db,
            admin_email=admin.email,
            action_type="UPDATE_CLIENT",
            entity_type="client",
            entity_id=client_id,
            details=payload.model_dump(exclude_none=True),
        )
        return updated


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: str,
    admin: AdminPrincipal = Depends(require_admin),
):
    """
    Safe client deletion verifying foreign key integrity.
    Rejects deletion with HTTP 409 Conflict if the client has associated bookings or packages.
    """
    async with get_db() as db:
        existing = await client_repo.get_client_by_id(db, client_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Client not found",
            )

        deps = await client_repo.get_client_dependencies(db, client_id)
        bookings_count = deps["bookings_count"]
        packages_count = deps["packages_count"]

        if bookings_count > 0 or packages_count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot delete client: client has {bookings_count} associated booking(s) "
                    f"and {packages_count} package(s)."
                ),
            )

        await client_repo.delete_client(db, client_id)

        await record_admin_audit(
            db,
            admin_email=admin.email,
            action_type="DELETE_CLIENT",
            entity_type="client",
            entity_id=client_id,
            details={
                "full_name": existing.full_name,
                "phone_whatsapp": existing.phone_whatsapp,
            },
        )
