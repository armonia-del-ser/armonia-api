from __future__ import annotations

import json
from typing import Annotated

from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_origins(v: str | list[str]) -> list[str]:
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except Exception:
            pass
        return [x.strip() for x in v.split(",") if x.strip()]
    return list(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "file:local.db"
    database_auth_token: str | None = None

    # Application
    environment: str = "development"
    port: int = 8000
    host: str = "0.0.0.0"
    cors_origins: Annotated[list[str], BeforeValidator(_parse_origins)] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    # Security
    admin_api_key: str = "dev-secret-key-change-in-production"

    # Business profile (Armonía del Ser)
    therapist_name: str = "Jazmín"
    business_name: str = "Armonía del Ser"
    whatsapp_phone: str = "521XXXXXXXXXX"
    spei_clabe: str = "012345678901234567"
    spei_bank: str = "BBVA"
    spei_beneficiary: str = "Jazmín"

    # Google Calendar
    gcal_calendar_id: str = "primary"
    google_service_account_json: str | None = None


settings = Settings()
