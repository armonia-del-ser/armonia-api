from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

import libsql_client
from fastapi import HTTPException, Request, status
from sqlmodel import Session

from app.core.config import AuthProvider, settings
from app.db.database import get_db, get_engine, row_to_dict
from app.models.admin import RoleEnum
from app.repositories.admin import mirror_admin_actor
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


# --- Pluggable authentication strategy (ADR-0006) ---------------------------------------
#
# Each adapter inspects only its own credentials and returns:
#   * AdminPrincipal -> authenticated and authorized
#   * None           -> its credentials are absent (lets require_admin try a fallback / 401)
# and raises HTTPException when credentials are present but invalid or unauthorized.

# Highest privilege first; exact (case-insensitive) LLDAP group names.
PROXY_GROUP_ROLES: tuple[tuple[str, RoleEnum], ...] = (
    ("armonia-owner", RoleEnum.OWNER),
    ("armonia-admin", RoleEnum.ADMIN),
    ("armonia-assistant", RoleEnum.ASSISTANT),
)
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def resolve_role_from_groups(raw_groups: str | None) -> RoleEnum | None:
    """Map Authelia's comma-separated `Remote-Groups` to the highest-privilege RoleEnum."""
    if not raw_groups:
        return None
    groups = {g.strip().lower() for g in raw_groups.split(",") if g.strip()}
    for group_name, role in PROXY_GROUP_ROLES:
        if group_name in groups:
            return role
    return None


class AuthAdapter(Protocol):
    async def authenticate(self, request: Request) -> AdminPrincipal | None: ...


async def _require_allowlisted(email: str) -> AdminPrincipal:
    async with get_db() as client:
        principal = await get_allowlisted_admin(client, email)
    if not principal:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"El correo '{email}' no está autorizado en la lista de administradores activos.",
        )
    return principal


class ProxyHeaderAdapter:
    """
    Authelia/LLDAP forward-auth. Identity and role come exclusively from Remote-* headers;
    reads perform zero database queries. On unsafe methods the principal is mirrored into
    `admin_allowlist` so audited writes keep FK integrity (ADR-0006).

    SECURITY: only enable when the API is reachable exclusively through the proxy, which must
    strip client-supplied Remote-* headers.
    """

    async def authenticate(self, request: Request) -> AdminPrincipal | None:
        raw_identity = request.headers.get("Remote-Email") or request.headers.get("Remote-User")
        email = (raw_identity or "").strip().lower()
        if not email:
            return None

        role = resolve_role_from_groups(request.headers.get("Remote-Groups"))
        if role is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"El usuario '{email}' no pertenece a ningún grupo armonia-* autorizado.",
            )

        full_name = (request.headers.get("Remote-Name") or "").strip() or email
        principal = AdminPrincipal(email=email, full_name=full_name, role=role.value)

        if request.method.upper() not in SAFE_METHODS:
            with Session(get_engine()) as session:
                mirror_admin_actor(session, email=email, full_name=full_name, role=role.value)
        return principal


class GoogleOAuthAdapter:
    """HMAC session token (Bearer header or HttpOnly cookie) verified against the allowlist."""

    async def authenticate(self, request: Request) -> AdminPrincipal | None:
        auth_header = request.headers.get("Authorization", "")
        token: str | None = None
        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()
        elif SESSION_COOKIE_NAME in request.cookies:
            token = request.cookies.get(SESSION_COOKIE_NAME)
        if not token:
            return None

        try:
            email = verify_session_token(token)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Sesión inválida o expirada: {exc}",
            ) from exc
        return await _require_allowlisted(email)


class DevKeyAdapter:
    """X-Admin-Key (+ optional X-Admin-Email) for tests, CLI, and local dashboard development."""

    async def authenticate(self, request: Request) -> AdminPrincipal | None:
        admin_key = request.headers.get("X-Admin-Key")
        if not admin_key:
            return None
        if not hmac.compare_digest(admin_key, settings.admin_api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Clave de administrador inválida.",
            )

        admin_email_hdr = (request.headers.get("X-Admin-Email") or "").strip().lower()
        email = admin_email_hdr or (
            settings.admin_bootstrap_emails[0].strip().lower()
            if settings.admin_bootstrap_emails
            else ""
        )
        if not email:
            return None
        return await _require_allowlisted(email)


AUTH_ADAPTERS: dict[AuthProvider, AuthAdapter] = {
    AuthProvider.PROXY_HEADERS: ProxyHeaderAdapter(),
    AuthProvider.GOOGLE_OAUTH: GoogleOAuthAdapter(),
    AuthProvider.DEV_KEY: DevKeyAdapter(),
}


def resolve_adapter_chain() -> list[AuthAdapter]:
    """Configured provider first; dev_key fallback only outside production."""
    primary = AuthProvider(settings.auth_provider)
    chain = [AUTH_ADAPTERS[primary]]
    if primary is not AuthProvider.DEV_KEY and settings.environment != "production":
        chain.append(AUTH_ADAPTERS[AuthProvider.DEV_KEY])
    return chain


async def require_admin(request: Request) -> AdminPrincipal:
    """
    FastAPI dependency yielding a uniform AdminPrincipal regardless of identity provider
    (`settings.auth_provider`). Routers and services never inspect credentials themselves.
    """
    for adapter in resolve_adapter_chain():
        principal = await adapter.authenticate(request)
        if principal is not None:
            return principal

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Autenticación de administrador requerida.",
    )
