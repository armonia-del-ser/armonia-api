from __future__ import annotations

import hmac
import secrets
import urllib.parse
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.auth import (
    OAUTH_STATE_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    create_session_token,
    get_allowlisted_admin,
    record_admin_audit,
    require_admin,
)
from app.core.config import settings
from app.db.database import get_db, result_to_dicts, row_to_dict
from app.schemas.auth import (
    AdminAllowlistCreate,
    AdminAllowlistUpdate,
    AdminPrincipal,
    AuditLogRead,
)

router = APIRouter(prefix="/auth", tags=["Authentication & Admin Allowlist"])

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


@router.get("/google/login")
async def google_oauth_login():
    """
    Initiate backend-driven Google OAuth2 Authorization Code flow.
    Redirects the administrator to Google's consent screen with a signed CSRF state cookie.
    """
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth credentials are not configured on the backend.",
        )

    state = secrets.token_urlsafe(32)
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    url = f"{GOOGLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"
    response = RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        value=state,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        max_age=600,
    )
    return response


@router.get("/google/callback")
async def google_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
):
    """
    Google OAuth2 callback:
    1. Validates CSRF state cookie.
    2. Exchanges authorization code for tokens on the server.
    3. Verifies Google userinfo (email_verified == True).
    4. Checks email against Turso's admin_allowlist table.
    5. Issues an HttpOnly signed session cookie and redirects to armonia-dashboard.
    """
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing code or state parameter in OAuth callback.",
        )

    expected_state = request.cookies.get(OAUTH_STATE_COOKIE_NAME)
    if not expected_state or not hmac.compare_digest(expected_state, state):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state parameter.",
        )

    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth credentials are not configured.",
        )

    async with httpx.AsyncClient(timeout=10.0) as http_client:
        token_res = await http_client.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "redirect_uri": settings.google_oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_res.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Failed to exchange Google OAuth authorization code.",
            )
        token_data = token_res.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google OAuth response did not include an access token.",
            )

        userinfo_res = await http_client.get(
            GOOGLE_USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_res.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Failed to fetch verified user profile from Google.",
            )
        userinfo = userinfo_res.json()

    email = str(userinfo.get("email", "")).strip().lower()
    email_verified = bool(userinfo.get("email_verified", False))
    if not email or not email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Google account email is missing or not verified.",
        )

    async with get_db() as client:
        principal = await get_allowlisted_admin(client, email)
        if not principal:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"El correo '{email}' no está en la lista de administradores autorizados.",
            )
        now = datetime.now(UTC).isoformat()
        await client.execute(
            "UPDATE admin_allowlist SET last_login_at = ? WHERE lower(email) = ?;",
            [now, email],
        )

    session_token = create_session_token(principal.email)
    redirect = RedirectResponse(
        url=settings.dashboard_origin_url, status_code=status.HTTP_302_FOUND
    )
    redirect.delete_cookie(OAUTH_STATE_COOKIE_NAME)
    redirect.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        max_age=settings.session_ttl_seconds,
    )
    return redirect


@router.get("/me", response_model=AdminPrincipal)
async def get_current_admin(admin: AdminPrincipal = Depends(require_admin)):
    """Return the currently authenticated and allowlisted administrator."""
    return admin


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    """Clear the administrator session cookie."""
    response.delete_cookie(SESSION_COOKIE_NAME)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/allowlist", response_model=list[AdminPrincipal])
async def list_allowlist(admin: AdminPrincipal = Depends(require_admin)):
    """List all administrator entries in Turso's admin_allowlist table."""
    async with get_db() as client:
        res = await client.execute(
            "SELECT email, full_name, role, is_active, last_login_at FROM admin_allowlist ORDER BY created_at ASC;"
        )
        rows = result_to_dicts(res)
        return [
            AdminPrincipal(
                email=str(r["email"]),
                full_name=str(r["full_name"]),
                role=r["role"],
                is_active=bool(r.get("is_active", 0)),
                last_login_at=r.get("last_login_at"),
            )
            for r in rows
        ]


@router.post("/allowlist", response_model=AdminPrincipal, status_code=status.HTTP_201_CREATED)
async def add_to_allowlist(
    payload: AdminAllowlistCreate,
    admin: AdminPrincipal = Depends(require_admin),
):
    """Add or reactivate an administrator in Turso's admin_allowlist table."""
    normalized_email = payload.email.strip().lower()
    async with get_db() as client:
        await client.execute(
            """
            INSERT INTO admin_allowlist (email, full_name, role, is_active)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                full_name = excluded.full_name,
                role = excluded.role,
                is_active = excluded.is_active;
            """,
            [normalized_email, payload.full_name, payload.role, 1 if payload.is_active else 0],
        )
        await record_admin_audit(
            client,
            admin_email=admin.email,
            action_type="UPSERT_ALLOWLIST",
            entity_type="admin_allowlist",
            entity_id=normalized_email,
            details={"role": payload.role, "is_active": payload.is_active},
        )
        res = await client.execute(
            "SELECT email, full_name, role, is_active, last_login_at FROM admin_allowlist WHERE email = ? LIMIT 1;",
            [normalized_email],
        )
        r = row_to_dict(res, res.rows[0])
        return AdminPrincipal(
            email=str(r["email"]),
            full_name=str(r["full_name"]),
            role=r["role"],
            is_active=bool(r.get("is_active", 0)),
            last_login_at=r.get("last_login_at"),
        )


@router.patch("/allowlist/{email}", response_model=AdminPrincipal)
async def update_allowlist_entry(
    email: str,
    payload: AdminAllowlistUpdate,
    admin: AdminPrincipal = Depends(require_admin),
):
    """Update role, name, or active status for an administrator in Turso."""
    normalized_email = email.strip().lower()
    async with get_db() as client:
        res = await client.execute(
            "SELECT * FROM admin_allowlist WHERE lower(email) = ? LIMIT 1;",
            [normalized_email],
        )
        if not res.rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Administrator email not found in allowlist.",
            )
        current = row_to_dict(res, res.rows[0])
        new_name = payload.full_name if payload.full_name is not None else current["full_name"]
        new_role = payload.role if payload.role is not None else current["role"]
        new_active = (
            (1 if payload.is_active else 0)
            if payload.is_active is not None
            else int(current["is_active"])
        )

        await client.execute(
            "UPDATE admin_allowlist SET full_name = ?, role = ?, is_active = ? WHERE lower(email) = ?;",
            [new_name, new_role, new_active, normalized_email],
        )
        await record_admin_audit(
            client,
            admin_email=admin.email,
            action_type="UPDATE_ALLOWLIST",
            entity_type="admin_allowlist",
            entity_id=normalized_email,
            details={"full_name": new_name, "role": new_role, "is_active": bool(new_active)},
        )
        updated_res = await client.execute(
            "SELECT email, full_name, role, is_active, last_login_at FROM admin_allowlist WHERE lower(email) = ? LIMIT 1;",
            [normalized_email],
        )
        r = row_to_dict(updated_res, updated_res.rows[0])
        return AdminPrincipal(
            email=str(r["email"]),
            full_name=str(r["full_name"]),
            role=r["role"],
            is_active=bool(r.get("is_active", 0)),
            last_login_at=r.get("last_login_at"),
        )


@router.get("/audit-log", response_model=list[AuditLogRead])
async def list_audit_log(
    entity_id: str | None = None,
    limit: int = 50,
    admin: AdminPrincipal = Depends(require_admin),
):
    """Retrieve recent administrative actions recorded in admin_audit_log."""
    async with get_db() as client:
        if entity_id:
            res = await client.execute(
                "SELECT * FROM admin_audit_log WHERE entity_id = ? ORDER BY created_at DESC LIMIT ?;",
                [entity_id, limit],
            )
        else:
            res = await client.execute(
                "SELECT * FROM admin_audit_log ORDER BY created_at DESC LIMIT ?;",
                [limit],
            )
        return [AuditLogRead(**r) for r in result_to_dicts(res)]
