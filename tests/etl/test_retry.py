"""Unit tests for etl.utils.retry."""

from unittest.mock import AsyncMock, patch

import pytest

from etl.utils.retry import with_exponential_backoff


class TestWithExponentialBackoff:
    async def test_success_on_first_attempt(self):
        op = AsyncMock(return_value="ok")
        result = await with_exponential_backoff(
            op,
            max_retries=3,
            retryable_exceptions=(ValueError,),
            operation_name="test",
        )
        assert result == "ok"
        op.assert_called_once()

    async def test_retries_on_retryable_then_succeeds(self):
        attempts = []

        async def flaky():
            attempts.append(1)
            if len(attempts) < 3:
                raise ValueError("transient")
            return "finally"

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await with_exponential_backoff(
                flaky,
                max_retries=5,
                retryable_exceptions=(ValueError,),
                operation_name="test",
            )
        assert result == "finally"
        assert len(attempts) == 3

    async def test_reraises_after_max_retries(self):
        async def always_fails():
            raise ValueError("permanent")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="permanent"):
                await with_exponential_backoff(
                    always_fails,
                    max_retries=3,
                    retryable_exceptions=(ValueError,),
                    operation_name="test",
                )

    async def test_non_retryable_propagates_immediately(self):
        attempts = []

        async def raises_keyerror():
            attempts.append(1)
            raise KeyError("not retryable")

        with pytest.raises(KeyError):
            await with_exponential_backoff(
                raises_keyerror,
                max_retries=5,
                retryable_exceptions=(ValueError,),
                operation_name="test",
            )
        assert len(attempts) == 1  # no retries

    async def test_exponential_backoff_durations(self):
        """Wait time should be 2^attempt: 1s, 2s, 4s for first 3 retries."""
        waits: list[float] = []

        async def fake_sleep(seconds: float):
            waits.append(seconds)

        async def always_fails():
            raise ValueError("x")

        with patch("asyncio.sleep", side_effect=fake_sleep):
            with pytest.raises(ValueError):
                await with_exponential_backoff(
                    always_fails,
                    max_retries=4,
                    retryable_exceptions=(ValueError,),
                    operation_name="test",
                )
        # max_retries=4 → 3 sleeps (between attempts), each 2^attempt
        assert waits == [1, 2, 4]
