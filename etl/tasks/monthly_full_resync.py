"""Monthly full re-sync — safety net against drift from nightly_sync.

Clears the local RC file cache (forces fresh monthly downloads), runs ``full_import``
with ``force=True`` to UPSERT everything, then marks addresses whose ``synced_at``
predates this run as deleted (they're no longer in the current RC dump).

Triggered by cron: ``0 3 1 * *`` (1st of each month at 03:00).
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.logging_config import configure_logging
from etl.config import settings
from etl.tasks.full_import import run as full_import_run
from etl.utils.time import utcnow_naive

log = logging.getLogger(__name__)

_CACHE_DIR = Path(settings.etl_cache_dir)
_CACHE_PATTERNS = ["rc_*.csv", "rc_*.json", "adr_*.zip"]


def _clear_cache() -> None:
    """Delete all cached RC files to force fresh monthly downloads."""
    cleared: list[str] = []
    for pattern in _CACHE_PATTERNS:
        for f in _CACHE_DIR.glob(pattern):
            try:
                f.unlink()
                cleared.append(f.name)
            except OSError as exc:
                log.warning("Could not delete cache file %s: %s", f, exc)
    if cleared:
        log.info("Cleared cache: %s", ", ".join(cleared))
    else:
        log.info("Cache was already empty.")


async def _mark_deleted(sync_start: datetime) -> int:
    """Mark addresses NOT seen in this resync as deleted.

    Any address with ``synced_at < sync_start`` was not upserted during this run,
    meaning it no longer exists in the current RC data.
    """
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                text(
                    "UPDATE addresses SET deleted_at = :now "
                    "WHERE synced_at < :sync_start AND deleted_at IS NULL"
                ),
                {"now": utcnow_naive(), "sync_start": sync_start},
            )
            await session.commit()
        except Exception as exc:
            log.error("Failed to mark stale addresses as deleted: %s", exc)
            raise
        return result.rowcount


async def run() -> None:
    """Run monthly full resync. Idempotent: safe to re-run."""
    log.info("=== Monthly full resync started ===")

    _clear_cache()

    sync_start = utcnow_naive()
    log.info("Sync start timestamp: %s", sync_start.isoformat())

    log.info("Running full import (force=True)...")
    await full_import_run(force=True)

    log.info("Marking stale addresses as deleted (synced_at < %s)...", sync_start.isoformat())
    deleted = await _mark_deleted(sync_start)
    log.info("  %d addresses marked deleted_at", deleted)

    log.info("=== Monthly full resync done ===")


if __name__ == "__main__":
    configure_logging()
    asyncio.run(run())
