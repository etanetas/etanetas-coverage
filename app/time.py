"""Project-wide UTC time helpers.

Always use these instead of `datetime.now()` — the bare call returns a
naive datetime in local TZ which silently desyncs across server timezones.

Note: values are returned as **naive datetimes in UTC** because the current
DB schema uses `TIMESTAMP WITHOUT TIME ZONE` columns. After columns migrate
to `TIMESTAMPTZ`, switch this helper to `datetime.now(UTC)`.
"""
from datetime import UTC, datetime


def now() -> datetime:
    """Return the current UTC time as a naive datetime (UTC value, no tzinfo)."""
    return datetime.now(UTC).replace(tzinfo=None)
