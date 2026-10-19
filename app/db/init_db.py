from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from app.core.config import settings
from app.db.database import get_db

SCHEMA_FILE = Path(__file__).parent / "schema.sql"

INITIAL_SERVICES = [
    {
        "id": str(uuid.uuid4()),
        "slug": "circulo-cacao-presencial",
        "name": "Círculo de Cacao (Presencial)",
        "description": "Espacio de reconexión con medicina de cacao, meditación y trabajo interior.",
        "service_type": "GROUP",
        "modality": "PRESENCIAL",
        "default_schedule": "Lunes 6:00 p. m.",
        "price_mxn": 350,
        "max_capacity": 15,
        "duration_minutes": 120,
    },
    {
        "id": str(uuid.uuid4()),
        "slug": "meditacion-cuencos-martes",
        "name": "Meditación con cuencos (Martes)",
        "description": "Sesión de armonización sonora con cuencos tibetanos.",
        "service_type": "GROUP",
        "modality": "PRESENCIAL",
        "default_schedule": "Martes 7:00 a. m.",
        "price_mxn": 200,
        "max_capacity": 12,
        "duration_minutes": 60,
    },
    {
        "id": str(uuid.uuid4()),
        "slug": "meditacion-ejercicios-conscientes",
        "name": "Meditación con ejercicios conscientes",
        "description": "Movimiento consciente y respiración para calmar la mente y armonizar tu energía.",
        "service_type": "GROUP",
        "modality": "PRESENCIAL",
        "default_schedule": "Martes 8:00 a. m.",
        "price_mxn": 200,
        "max_capacity": 12,
        "duration_minutes": 60,
    },
    {
        "id": str(uuid.uuid4()),
        "slug": "circulo-cacao-online",
        "name": "Círculo de Cacao (Online)",
        "description": "Conexión a distancia con la energía del cacao y círculo de sanación.",
        "service_type": "GROUP",
        "modality": "ONLINE",
        "default_schedule": "Martes 7:00 p. m.",
        "price_mxn": 300,
        "max_capacity": 25,
        "duration_minutes": 120,
    },
    {
        "id": str(uuid.uuid4()),
        "slug": "constelaciones-familiares-online",
        "name": "Constelaciones Familiares (Online)",
        "description": "Terapia sistémica grupal virtual para sanar dinámicas inconscientes familiares.",
        "service_type": "GROUP",
        "modality": "ONLINE",
        "default_schedule": "Jueves 7:00 p. m.",
        "price_mxn": 450,
        "max_capacity": 20,
        "duration_minutes": 120,
    },
    {
        "id": str(uuid.uuid4()),
        "slug": "clase-4-elementos-tarot",
        "name": "Clase de los 4 Elementos y Tarot",
        "description": "Exploración de la cosmovisión de los cuatro elementos integrada a la sabiduría del tarot.",
        "service_type": "GROUP",
        "modality": "ONLINE",
        "default_schedule": "Viernes 9:00 a. m.",
        "price_mxn": 300,
        "max_capacity": 15,
        "duration_minutes": 90,
    },
    {
        "id": str(uuid.uuid4()),
        "slug": "meditacion-guiada-sabado",
        "name": "Meditación guiada (Sábado)",
        "description": "Meditación guiada matutina para iniciar el fin de semana en paz y presencia.",
        "service_type": "GROUP",
        "modality": "PRESENCIAL",
        "default_schedule": "Sábados 7:00 a. m.",
        "price_mxn": 200,
        "max_capacity": 15,
        "duration_minutes": 60,
    },
    {
        "id": str(uuid.uuid4()),
        "slug": "meditacion-cuencos-sabado",
        "name": "Meditación con cuencos (Sábado)",
        "description": "Vibración y baño de sonido con cuencos tibetanos.",
        "service_type": "GROUP",
        "modality": "PRESENCIAL",
        "default_schedule": "Sábados 8:00 a. m.",
        "price_mxn": 200,
        "max_capacity": 15,
        "duration_minutes": 60,
    },
    {
        "id": str(uuid.uuid4()),
        "slug": "atencion-psicologica-individual",
        "name": "Atención Psicológica Individual",
        "description": "Sesión individual de psicoterapia personalizada (presencial u online).",
        "service_type": "ONE_ON_ONE",
        "modality": "PRESENCIAL",
        "default_schedule": "Con cita previa",
        "price_mxn": 600,
        "max_capacity": 1,
        "duration_minutes": 60,
        "buffer_minutes": 15,
    },
]


async def init_schema_and_seed():
    """Execute DDL statements and seed initial services and bootstrap administrators."""
    async with get_db() as client:
        with open(SCHEMA_FILE, encoding="utf-8") as f:
            ddl = f.read()

        statements = [stmt.strip() for stmt in ddl.split(";") if stmt.strip()]
        for stmt in statements:
            await client.execute(stmt)

        # Seed bootstrap administrators idempotently
        for idx, raw_email in enumerate(settings.admin_bootstrap_emails):
            email = raw_email.strip().lower()
            if not email:
                continue
            role = "OWNER" if idx == 0 else "ASSISTANT"
            full_name = settings.therapist_name if idx == 0 else "Asistente Armonía del Ser"
            await client.execute(
                """
                INSERT OR IGNORE INTO admin_allowlist (email, full_name, role, is_active)
                VALUES (?, ?, ?, 1);
                """,
                [email, full_name, role],
            )

        # Check if services already seeded
        res = await client.execute("SELECT COUNT(*) AS count FROM services;")
        count = res.rows[0][0]
        if count == 0:
            print("🌱 Seeding initial services from Armonía del Ser flyer...")
            insert_query = """
                INSERT INTO services (
                    id, slug, name, description, service_type, modality,
                    default_schedule, price_mxn, max_capacity, duration_minutes, buffer_minutes, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1);
            """
            for s in INITIAL_SERVICES:
                await client.execute(
                    insert_query,
                    [
                        s["id"],
                        s["slug"],
                        s["name"],
                        s["description"],
                        s["service_type"],
                        s["modality"],
                        s["default_schedule"],
                        s["price_mxn"],
                        s["max_capacity"],
                        s["duration_minutes"],
                        s.get("buffer_minutes", 0),
                    ],
                )
            print(f"✅ Successfully seeded {len(INITIAL_SERVICES)} services!")
        else:
            print(f"ℹ️  Services table already has {count} entries, skipping seed.")


if __name__ == "__main__":
    asyncio.run(init_schema_and_seed())
