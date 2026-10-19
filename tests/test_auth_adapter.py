from __future__ import annotations

import pytest
from sqlmodel import Session, select

from app.core.auth import create_session_token
from app.core.config import AuthProvider, settings
from app.db.database import get_engine
from app.models.admin import AdminAllowlist

OWNER_EMAIL = "jasmin@armoniadelser.mx"


def _proxy_headers(
    email: str | None = "operadora@homelab.lan",
    groups: str | None = "users,armonia-assistant",
    name: str | None = "Operadora Homelab",
    *,
    user: str | None = None,
) -> dict[str, str]:
    headers: dict[str, str] = {}
    if email is not None:
        headers["Remote-Email"] = email
    if user is not None:
        headers["Remote-User"] = user
    if groups is not None:
        headers["Remote-Groups"] = groups
    if name is not None:
        headers["Remote-Name"] = name
    return headers


def _bearer(email: str = OWNER_EMAIL) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_session_token(email)}"}


def _dev_key(email: str | None = OWNER_EMAIL, key: str | None = None) -> dict[str, str]:
    headers = {"X-Admin-Key": key if key is not None else settings.admin_api_key}
    if email is not None:
        headers["X-Admin-Email"] = email
    return headers


def _allowlist_row(email: str) -> AdminAllowlist | None:
    with Session(get_engine()) as session:
        return session.exec(select(AdminAllowlist).where(AdminAllowlist.email == email)).first()


@pytest.fixture
def proxy_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.PROXY_HEADERS)


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")


# --- proxy_headers (Authelia + LLDAP) -------------------------------------------------


def test_proxy_headers_build_principal_from_authelia_headers(client, proxy_mode):
    res = client.get("/auth/me", headers=_proxy_headers())
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == "operadora@homelab.lan"
    assert body["full_name"] == "Operadora Homelab"
    assert body["role"] == "ASSISTANT"


def test_proxy_headers_normalize_email_and_fall_back_to_remote_user(client, proxy_mode):
    res = client.get(
        "/auth/me",
        headers=_proxy_headers(email=None, user="  Owner@Homelab.LAN ", groups="armonia-owner"),
    )
    assert res.status_code == 200
    assert res.json()["email"] == "owner@homelab.lan"
    assert res.json()["role"] == "OWNER"


def test_proxy_headers_fall_back_to_email_when_remote_name_missing(client, proxy_mode):
    res = client.get("/auth/me", headers=_proxy_headers(name=None))
    assert res.status_code == 200
    assert res.json()["full_name"] == "operadora@homelab.lan"


def test_proxy_headers_without_identity_are_unauthenticated(client, proxy_mode):
    res = client.get("/auth/me", headers=_proxy_headers(email=None, user=None))
    assert res.status_code == 401


def test_proxy_headers_without_armonia_group_are_forbidden(client, proxy_mode):
    res = client.get("/auth/me", headers=_proxy_headers(groups="users,family"))
    assert res.status_code == 403


def test_proxy_headers_reads_never_touch_the_allowlist(client, proxy_mode):
    email = "lector.solo@homelab.lan"
    res = client.get("/bookings/follow-up-queue", headers=_proxy_headers(email=email))
    assert res.status_code == 200
    assert _allowlist_row(email) is None


def test_proxy_headers_mirror_principal_into_allowlist_on_first_write(client, proxy_mode):
    email = "escritora@homelab.lan"
    assert _allowlist_row(email) is None

    res = client.post(
        "/auth/allowlist",
        headers=_proxy_headers(email=email, groups="armonia-owner", name="Escritora"),
        json={"email": "nueva.asistente@armoniadelser.mx", "full_name": "Nueva Asistente"},
    )
    assert res.status_code == 201

    mirrored = _allowlist_row(email)
    assert mirrored is not None
    assert mirrored.role == "OWNER"
    assert mirrored.full_name == "Escritora"
    assert mirrored.last_login_at is not None

    # Audit trail references the mirrored actor (FK target exists)
    audit = client.get(
        "/auth/audit-log?entity_id=nueva.asistente@armoniadelser.mx",
        headers=_proxy_headers(email=email, groups="armonia-owner"),
    ).json()
    assert audit[0]["admin_email"] == email


def test_proxy_mirror_tracks_role_changes_from_lldap(client, proxy_mode):
    email = "promovida@homelab.lan"
    for groups in ("armonia-assistant", "armonia-admin"):
        res = client.patch(
            f"/auth/allowlist/{OWNER_EMAIL}",
            headers=_proxy_headers(email=email, groups=groups),
            json={},
        )
        assert res.status_code == 200
    mirrored = _allowlist_row(email)
    assert mirrored is not None
    assert mirrored.role == "ADMIN"


def test_proxy_mode_ignores_bearer_tokens_in_production(client, proxy_mode, production):
    assert client.get("/auth/me", headers=_bearer()).status_code == 401


def test_proxy_mode_rejects_dev_key_in_production(client, proxy_mode, production):
    assert client.get("/auth/me", headers=_dev_key()).status_code == 401


def test_proxy_mode_allows_dev_key_fallback_outside_production(client, proxy_mode):
    res = client.get("/auth/me", headers=_dev_key())
    assert res.status_code == 200
    assert res.json()["email"] == OWNER_EMAIL


# --- google_oauth -------------------------------------------------------------------


def test_google_oauth_ignores_spoofed_proxy_headers(client):
    assert settings.auth_provider == AuthProvider.GOOGLE_OAUTH
    res = client.get("/auth/me", headers=_proxy_headers(groups="armonia-owner"))
    assert res.status_code == 401


def test_google_oauth_rejects_invalid_session_token(client):
    res = client.get("/auth/me", headers={"Authorization": "Bearer not.a-valid-token"})
    assert res.status_code == 401


def test_google_oauth_accepts_session_cookie(client):
    client.cookies.set("armonia_session", create_session_token(OWNER_EMAIL))
    try:
        res = client.get("/auth/me")
    finally:
        client.cookies.clear()
    assert res.status_code == 200
    assert res.json()["role"] == "OWNER"


def test_google_oauth_rejects_dev_key_in_production(client, production):
    assert client.get("/auth/me", headers=_dev_key()).status_code == 401


def test_google_oauth_session_still_works_in_production(client, production):
    assert client.get("/auth/me", headers=_bearer()).status_code == 200


# --- dev_key ------------------------------------------------------------------------


@pytest.fixture
def dev_key_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.DEV_KEY)


def test_dev_key_resolves_allowlisted_email(client, dev_key_mode):
    res = client.get("/auth/me", headers=_dev_key("asistente@armoniadelser.mx"))
    assert res.status_code == 200
    assert res.json()["role"] == "ASSISTANT"


def test_dev_key_without_email_uses_first_bootstrap_admin(client, dev_key_mode):
    res = client.get("/auth/me", headers=_dev_key(email=None))
    assert res.status_code == 200
    assert res.json()["email"] == settings.admin_bootstrap_emails[0]


def test_dev_key_with_wrong_key_is_unauthenticated(client, dev_key_mode):
    assert client.get("/auth/me", headers=_dev_key(key="wrong-key")).status_code == 401


def test_dev_key_with_non_allowlisted_email_is_forbidden(client, dev_key_mode):
    assert client.get("/auth/me", headers=_dev_key("intruder@example.com")).status_code == 403


def test_dev_key_mode_ignores_bearer_tokens(client, dev_key_mode):
    assert client.get("/auth/me", headers=_bearer()).status_code == 401
