import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.logging_config import configure_logging
from etl.tasks.full_import import run as full_import_run

log = logging.getLogger(__name__)

_CACHE_DIR = Path("etl/state/cache")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _clear_cache() -> None:
    """Delete all cached RC files to force fresh monthly downloads."""
    cleared = []
    for f in _CACHE_DIR.glob("rc_*.csv"):
        f.unlink()
        cleared.append(f.name)
    for f in _CACHE_DIR.glob("rc_*.json"):
        f.unlink()
        cleared.append(f.name)
    zip_file = _CACHE_DIR / "adr_gra_adresai_LT.zip"
    if zip_file.exists():
        zip_file.unlink()
        cleared.append(zip_file.name)
    if cleared:
        log.info("Cleared cache: %s", ", ".join(cleared))
    else:
        log.info("Cache was already empty.")


async def _mark_deleted(sync_start: datetime) -> int:
    """Mark addresses not seen in this resync as deleted.

    Any address with synced_at < sync_start was not upserted during this run —
    meaning it no longer exists in the current RC data.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "UPDATE addresses SET deleted_at = :now "
                "WHERE synced_at < :sync_start AND deleted_at IS NULL"
            ),
            {"now": _now(), "sync_start": sync_start},
        )
        await session.commit()
        return result.rowcount


async def run() -> None:
    log.info("=== Monthly full resync started ===")

    _clear_cache()

    sync_start = _now()
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
