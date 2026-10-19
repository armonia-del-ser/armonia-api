from datetime import UTC, datetime


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_iso_datetime(dt_str: str) -> datetime:
    """Parse an ISO 8601 string, normalizing naive datetimes to UTC."""
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt
