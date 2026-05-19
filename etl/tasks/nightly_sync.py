import asyncio
import logging
import socket
from datetime import UTC, date, datetime

from app.database import AsyncSessionLocal
from app.logging_config import configure_logging
from etl.config import settings
from etl.downloaders.spinta_client import SpintaClient
from etl.loaders.incremental_load import apply_adresas_changes, apply_pastatas_changes
from etl.notifications import send_alert
from etl.state_db import (
    get_last_cid,
    get_last_nightly_sync_date,
    save_cid,
    save_nightly_sync_date,
)

log = logging.getLogger(__name__)

_STALE_DAYS = settings.stale_sync_days
_HOST = socket.gethostname()


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


async def _check_staleness(last_sync_date: str | None) -> None:
    """Alert via Telegram if DB hasn't been synced in >7 days."""
    if not last_sync_date:
        return
    last = date.fromisoformat(last_sync_date)
    days_ago = (date.today() - last).days
    if days_ago > _STALE_DAYS:
        await send_alert(
            f"⚠️ <b>Etanetas ETL alert</b> [{_HOST}]\n"
            f"Address DB has not been updated for <b>{days_ago} days</b>.\n"
            f"Last successful sync: {last_sync_date}"
        )


async def run() -> None:
    async with AsyncSessionLocal() as session:
        last_sync_date = await get_last_nightly_sync_date(session)
        last_cid = await get_last_cid(session)

    # Idempotency: skip if already synced today (supports 3-cron retry pattern)
    if last_sync_date == _today():
        log.info("Nightly sync already completed today (%s). Exiting.", last_sync_date)
        return

    # Staleness alert
    await _check_staleness(last_sync_date)

    log.info("Starting nightly sync from cid=%d", last_cid)
    spinta = SpintaClient()

    adresas_changes: list[dict] = []
    pastatas_changes: list[dict] = []
    max_cid = last_cid

    log.info("Fetching adresai/Adresas changes...")
    async for rec in spinta.fetch_changes("adresai/Adresas", last_cid):
        max_cid = max(max_cid, rec["_cid"])
        adresas_changes.append(rec)
    log.info("  %d changes", len(adresas_changes))

    log.info("Fetching pastatas/Pastatas changes...")
    async for rec in spinta.fetch_changes("pastatas/Pastatas", last_cid):
        max_cid = max(max_cid, rec["_cid"])
        pastatas_changes.append(rec)
    log.info("  %d changes", len(pastatas_changes))

    if max_cid == last_cid:
        log.info("No new changes since cid=%d.", last_cid)
    else:
        log.info("Applying changes...")
        async with AsyncSessionLocal() as session:
            deleted_adr = await apply_adresas_changes(session, adresas_changes)
            upserted, deleted_pat = await apply_pastatas_changes(session, spinta, pastatas_changes)
            log.info("  upserted: %d, deleted_at: %d", upserted, deleted_adr + deleted_pat)
            await save_cid(session, max_cid)
            log.info("New _cid saved: %d", max_cid)

    async with AsyncSessionLocal() as session:
        await save_nightly_sync_date(session)

    log.info("Nightly sync done.")


async def main() -> None:
    """Entry point with error handling and Telegram alert on failure."""
    try:
        await run()
    except Exception as e:
        log.exception("Nightly sync failed: %s", e)
        await send_alert(
            f"🔴 <b>Etanetas nightly sync FAILED</b> [{_HOST}]\n"
            f"Error: <code>{type(e).__name__}: {e}</code>\n"
            f"Check logs. Next retry in 4h (cron 06:00)."
        )
        raise


if __name__ == "__main__":
    configure_logging()
    asyncio.run(main())
