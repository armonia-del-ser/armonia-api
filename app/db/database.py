from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

import libsql_client

from app.core.config import settings


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
