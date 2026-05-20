"""Unit tests for etl.utils.time."""

from datetime import UTC, datetime

from etl.utils.time import utcnow_naive


class TestUtcnowNaive:
    def test_returns_datetime(self):
        result = utcnow_naive()
        assert isinstance(result, datetime)

    def test_tzinfo_is_none(self):
        """Naive datetime — no tzinfo, suitable for TIMESTAMP (no TZ) columns."""
        result = utcnow_naive()
        assert result.tzinfo is None

    def test_close_to_real_utc_now(self):
        """Should be within a few seconds of actual UTC now."""
        from_util = utcnow_naive()
        from_stdlib = datetime.now(UTC).replace(tzinfo=None)
        delta = abs((from_stdlib - from_util).total_seconds())
        assert delta < 2.0, f"utcnow_naive() returned time off by {delta}s"
