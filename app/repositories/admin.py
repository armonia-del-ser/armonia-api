from __future__ import annotations

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from app.models.admin import AdminAllowlist
from app.services.timestamps import utc_now_iso


def mirror_admin_actor(session: Session, *, email: str, full_name: str, role: str) -> None:
    """
    Upsert an externally-authenticated actor (e.g. Authelia proxy user) into `admin_allowlist`
    so that actor columns (`admin_audit_log.admin_email`, `payments.acknowledged_by`, ...) keep
    referential integrity (ADR-0006).

    The identity provider is authoritative for name and role, so both are refreshed on every
    write. `is_active` is deliberately left untouched on conflict: mirroring records who acted,
    it never re-enables a row an operator disabled.
    """
    now = utc_now_iso()
    table = AdminAllowlist.__table__  # pyright: ignore[reportAttributeAccessIssue]
    stmt = sqlite_insert(table).values(
        email=email,
        full_name=full_name,
        role=role,
        is_active=True,
        created_at=now,
        last_login_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[table.c.email],
        set_={"full_name": full_name, "role": role, "last_login_at": now},
    )
    session.exec(stmt)  # pyright: ignore[reportCallIssue, reportArgumentType]
    session.commit()
