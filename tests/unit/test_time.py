from datetime import UTC, datetime, timezone
from app.time import now


def test_now_is_timezone_aware():
    n = now()
    assert n.tzinfo is not None
    assert n.utcoffset().total_seconds() == 0


def test_now_is_utc():
    assert now().tzinfo == UTC
