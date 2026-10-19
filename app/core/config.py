from __future__ import annotations

import json
from typing import Annotated

from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_str_list(v: str | list[str]) -> list[str]:
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
        return [x.strip() for x in v.split(",") if x.strip()]
    return [str(x).strip() for x in v if str(x).strip()]


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
    cors_origins: Annotated[list[str], BeforeValidator(_parse_str_list)] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    # Security & Google OAuth + Turso Allowlist
    admin_api_key: str = "dev-secret-key-change-in-production"
    session_secret_key: str = "dev-session-secret-change-in-production"
    session_ttl_seconds: int = 86400 * 7  # 7 days
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    google_oauth_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    dashboard_origin_url: str = "http://localhost:5173"
    admin_bootstrap_emails: Annotated[list[str], BeforeValidator(_parse_str_list)] = [
        "jasmin@armoniadelser.mx",
        "asistente@armoniadelser.mx",
    ]

    # Operational rules
    payment_followup_threshold_hours: int = 48

    # Business profile (Armonía del Ser)
    therapist_name: str = "Jasmin"
    business_name: str = "Armonía del Ser"
    whatsapp_phone: str = "527751487912"
    spei_clabe: str = "012345678901234567"
    spei_bank: str = "BBVA"
    spei_beneficiary: str = "Jasmin"

    # Google Calendar
    gcal_calendar_id: str = "primary"
    google_service_account_json: str | None = None


settings = Settings()
