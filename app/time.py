"""Project-wide timezone-aware time helpers.

Always use these instead of `datetime.now()` — the bare call returns a
naive datetime in local TZ and compares incorrectly against `timestamptz`
columns.
"""
from datetime import UTC, datetime


def now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)
