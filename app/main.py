from __future__ import annotations

import contextlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.init_db import init_schema_and_seed
from app.routers import auth, bookings, health, packages, payments, services


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure tables, bootstrap allowlist, and initial catalog are seeded on boot
    await init_schema_and_seed()
    yield


app = FastAPI(
    title="Armonía del Ser API",
    description=(
        "Operational source-of-truth backend sitting between Google Calendar, Turso, "
        "and the Admin Dashboard protected with Google OAuth + Turso allowlisting."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(services.router)
app.include_router(bookings.router)
app.include_router(packages.router)
app.include_router(payments.router)


@app.get("/")
def root():
    return {
        "service": settings.business_name,
        "tagline": "Cada día, un espacio para volver a ti",
        "docs_url": "/docs",
    }
