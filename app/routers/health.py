from __future__ import annotations

from fastapi import APIRouter, status

from app.db.database import get_db

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", status_code=status.HTTP_200_OK)
async def health_check():
    """Health check endpoint confirming service and database connectivity."""
    db_status = "ok"
    try:
        async with get_db() as client:
            await client.execute("SELECT 1;")
    except Exception as e:
        db_status = f"unhealthy: {e}"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "database": db_status,
        "service": "armonia-api",
    }
