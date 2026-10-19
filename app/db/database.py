from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Generator
from typing import Any

import libsql_client
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from app.core.config import settings


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:
        # Some drivers / libSQL dialects might not support raw cursor PRAGMA
        pass


def get_engine_url(url: str, auth_token: str | None = None) -> str:
    """Normalize database URL for SQLAlchemy / SQLModel engine compatibility."""
    if url.startswith("file:"):
        db_path = url.removeprefix("file:")
        return f"sqlite:///{db_path}"
    if url.startswith("libsql://"):
        cleaned = url.removeprefix("libsql://")
        base = f"sqlite+libsql://{cleaned}"
        if auth_token and "auth_token=" not in base:
            sep = "&" if "?" in base else "?"
            return f"{base}{sep}auth_token={auth_token}"
        return base
    if url.startswith("sqlite+libsql://"):
        if auth_token and "auth_token=" not in url:
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}auth_token={auth_token}"
        return url
    return url


_engine_cache: dict[str, Engine] = {}


def get_engine() -> Engine:
    """Retrieve or create a cached SQLModel Engine based on current settings."""
    engine_url = get_engine_url(settings.database_url, settings.database_auth_token)
    if engine_url not in _engine_cache:
        connect_args: dict[str, Any] = {}
        if engine_url.startswith("sqlite:") and "+libsql" not in engine_url:
            connect_args["check_same_thread"] = False
        _engine_cache[engine_url] = create_engine(engine_url, connect_args=connect_args)
    return _engine_cache[engine_url]


def get_session() -> Generator[Session]:
    """Dependency yielding a SQLModel Session for synchronous and async endpoints."""
    engine = get_engine()
    with Session(engine) as session:
        yield session


def get_client() -> libsql_client.Client:
    """Create a new async Turso/libSQL client based on current settings."""
    if settings.database_url.startswith("file:"):
        return libsql_client.create_client(settings.database_url)
    return libsql_client.create_client(
        url=settings.database_url,
        auth_token=settings.database_auth_token or "",
    )


@contextlib.asynccontextmanager
async def get_db() -> AsyncIterator[libsql_client.Client]:
    """Dependency / context manager for acquiring a database client."""
    client = get_client()
    try:
        yield client
    finally:
        await client.close()


def row_to_dict(result_set: libsql_client.ResultSet, row: libsql_client.Row) -> dict[str, Any]:
    """Helper to convert a libsql Row into a Python dictionary."""
    return {col: val for col, val in zip(result_set.columns, row, strict=False)}


def result_to_dicts(result_set: libsql_client.ResultSet) -> list[dict[str, Any]]:
    """Helper to convert all rows of a ResultSet into dictionaries."""
    return [row_to_dict(result_set, row) for row in result_set.rows]
