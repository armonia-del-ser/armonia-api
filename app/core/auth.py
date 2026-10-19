from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import libsql_client
from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.db.database import get_db, row_to_dict
from app.schemas.auth import AdminPrincipal

SESSION_COOKIE_NAME = "armonia_session"
OAUTH_STATE_COOKIE_NAME = "armonia_oauth_state"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


def create_session_token(email: str, ttl_seconds: int | None = None) -> str:
    """Create an HMAC-SHA256 signed session token for an authenticated admin email."""
    ttl = ttl_seconds if ttl_seconds is not None else settings.session_ttl_seconds
    payload = {
        "sub": email.strip().lower(),
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl,
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(
        settings.session_secret_key.encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    sig_b64 = _b64url_encode(sig)
    return f"{payload_b64}.{sig_b64}"


def verify_session_token(token: str) -> str:
    """Verify HMAC-SHA256 signature and expiration, returning the normalized admin email."""
    parts = token.split(".")
    if len(parts) != 2:
        raise ValueError("Invalid token format")
    payload_b64, sig_b64 = parts
    expected_sig = hmac.new(
        settings.session_secret_key.encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        actual_sig = _b64url_decode(sig_b64)
    except Exception as exc:
        raise ValueError("Invalid token signature encoding") from exc

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Token signature mismatch")

    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception as exc:
        raise ValueError("Invalid token payload") from exc

    exp = int(payload.get("exp", 0))
    if time.time() >= exp:
        raise ValueError("Session token has expired")

    email = str(payload.get("sub", "")).strip().lower()
    if not email:
        raise ValueError("Token missing subject email")
    return email


async def get_allowlisted_admin(client: libsql_client.Client, email: str) -> AdminPrincipal | None:
    """Look up an email in Turso's admin_allowlist table and return AdminPrincipal if active."""
    normalized = email.strip().lower()
    res = await client.execute(
        "SELECT email, full_name, role, is_active, last_login_at FROM admin_allowlist WHERE lower(email) = ? LIMIT 1;",
        [normalized],
    )
    if not res.rows:
        return None
    row = row_to_dict(res, res.rows[0])
    if not bool(row.get("is_active", 0)):
        return None
    return AdminPrincipal(
        email=str(row["email"]),
        full_name=str(row["full_name"]),
        role=row["role"],
        is_active=True,
        last_login_at=row.get("last_login_at"),
    )


async def record_admin_audit(
    client: libsql_client.Client,
    admin_email: str,
    action_type: str,
    entity_type: str,
    entity_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Write an immutable audit entry to admin_audit_log."""
    audit_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    details_json = json.dumps(details, ensure_ascii=False) if details else None
    await client.execute(
        """
        INSERT INTO admin_audit_log (id, admin_email, action_type, entity_type, entity_id, details_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        [audit_id, admin_email, action_type, entity_type, entity_id, details_json, now],
    )


async def require_admin(request: Request) -> AdminPrincipal:
    """
    FastAPI dependency enforcing Google OAuth session token OR dev/service key fallback,
    always verified against an active row in Turso's admin_allowlist table.
    """
    candidate_email: str | None = None

    # 1. Check Authorization: Bearer <session_token> or HttpOnly session cookie
    auth_header = request.headers.get("Authorization", "")
    token: str | None = None
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ").strip()
    elif SESSION_COOKIE_NAME in request.cookies:
        token = request.cookies.get(SESSION_COOKIE_NAME)

    if token:
        try:
            candidate_email = verify_session_token(token)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Sesión inválida o expirada: {exc}",
            ) from exc
    else:
        # 2. Check X-Admin-Key + X-Admin-Email fallback for automated tests / CLI
        admin_key = request.headers.get("X-Admin-Key")
        admin_email_hdr = request.headers.get("X-Admin-Email")
        if admin_key and hmac.compare_digest(admin_key, settings.admin_api_key):
            if admin_email_hdr:
                candidate_email = admin_email_hdr.strip().lower()
            elif settings.admin_bootstrap_emails:
                candidate_email = settings.admin_bootstrap_emails[0].strip().lower()

    if not candidate_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación de administrador requerida (Google OAuth).",
        )

    async with get_db() as client:
        principal = await get_allowlisted_admin(client, candidate_email)
        if not principal:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"El correo '{candidate_email}' no está autorizado en la lista de administradores activos.",
            )
        return principal
