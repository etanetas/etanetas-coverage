"""Shared retry-with-exponential-backoff for async operations."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)


async def with_exponential_backoff[T](
    operation: Callable[[], Awaitable[T]],
    *,
    max_retries: int,
    retryable_exceptions: tuple[type[BaseException], ...],
    operation_name: str = "operation",
) -> T:
    """Execute :operation:; on retryable exception retry with 2^attempt seconds wait.

    Re-raises the last exception after exhausting :max_retries:.
    Logs each retry as WARNING with attempt count, wait time, and exception type.

    Special handling for ``asyncio.CancelledError``: re-raised immediately if the
    current task is being genuinely cancelled (Ctrl+C), retried otherwise (server-side TCP drop).
    """
    for attempt in range(max_retries):
        try:
            return await operation()
        except retryable_exceptions as exc:
            if isinstance(exc, asyncio.CancelledError):
                task = asyncio.current_task()
                if task is not None and task.cancelling() > 0:
                    raise  # genuine Ctrl+C / task cancel — don't swallow
            if attempt == max_retries - 1:
                log.error("%s failed after %d attempts: %s", operation_name, max_retries, exc)
                raise
            wait_seconds = 2**attempt
            log.warning(
                "%s retry %d/%d after %s, waiting %ds",
                operation_name,
                attempt + 1,
                max_retries,
                type(exc).__name__,
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)
    raise RuntimeError("unreachable")
