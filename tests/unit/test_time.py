from datetime import UTC, datetime

from app.time import now


def test_now_is_naive():
    """Until columns migrate to TIMESTAMPTZ, helper returns naive UTC."""
    assert now().tzinfo is None


def test_now_returns_utc_value():
    """Value must be UTC (compare against datetime.now(UTC), allow ~1s skew)."""
    expected = datetime.now(UTC).replace(tzinfo=None)
    delta = abs((now() - expected).total_seconds())
    assert delta < 1.0
