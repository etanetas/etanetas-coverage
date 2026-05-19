"""Time utilities for ETL."""

from datetime import UTC, datetime


def utcnow_naive() -> datetime:
    """Return current UTC time as naive datetime (no tzinfo).

    Used for synced_at, updated_at columns which are stored as TIMESTAMP (no TZ).
    """
    return datetime.now(UTC).replace(tzinfo=None)
