from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated

from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthProvider(StrEnum):
    """Identity source strategy consumed by `app.core.auth.require_admin`."""

    PROXY_HEADERS = "proxy_headers"
    GOOGLE_OAUTH = "google_oauth"
    DEV_KEY = "dev_key"


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


def _parse_int_list(v: str | list[int]) -> list[int]:
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return [int(x) for x in parsed]
        except Exception:
            pass
        return [int(x.strip()) for x in v.split(",") if x.strip()]
    return [int(x) for x in v]


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

    # Security & Pluggable Authentication (ADR-0005, ADR-0006)
    # proxy_headers: trust Authelia Remote-* headers (API must only be reachable via the proxy)
    # google_oauth:  HMAC session token/cookie verified against Turso admin_allowlist
    # dev_key:       X-Admin-Key (+ X-Admin-Email) verified against admin_allowlist
    # Outside production, dev_key is also tried as a fallback when the primary finds no credentials.
    auth_provider: AuthProvider = AuthProvider.GOOGLE_OAUTH
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

    # Business hours & availability engine (ADR-0003)
    business_timezone: str = "America/Mexico_City"
    availability_open_time: str = "09:00"
    availability_close_time: str = "19:00"
    availability_slot_step_minutes: int = 30
    availability_working_weekdays: Annotated[list[int], BeforeValidator(_parse_int_list)] = [
        0,
        1,
        2,
        3,
        4,
    ]  # Mon-Fri
    availability_max_range_days: int = 60

    # Google Calendar
    gcal_calendar_id: str = "primary"
    google_service_account_json: str | None = None


settings = Settings()
