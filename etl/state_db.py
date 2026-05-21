"""ETL state persistence in the ``etl_state`` table.

Stores three keys:
 - ``adresai_cid``: last Spinta ``_cid`` processed (cursor for nightly sync)
 - ``full_import_step``: last completed step of full_import (resume checkpoint)
 - ``last_nightly_sync_date``: ISO date of last successful nightly sync (idempotency)
"""

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.etl_state import EtlState
from etl.utils.time import utcnow_naive

_CID_KEY = "adresai_cid"
_STEP_KEY = "full_import_step"
_LAST_SYNC_KEY = "last_nightly_sync_date"  # ISO date YYYY-MM-DD

# Ordered steps — used to skip already-completed steps on resume
IMPORT_STEPS = [
    "counties",
    "municipalities",
    "localities",
    "streets",
    "points",
    "addresses",
    # "premises" — skipped: ISP operates at building level, not per-apartment
    "boundaries",
    "axes",
    "cid",
]


async def _get(session: AsyncSession, key: str) -> str | None:
    return await session.scalar(select(EtlState.value).where(EtlState.key == key))


async def _set(session: AsyncSession, key: str, value: str) -> None:
    now = utcnow_naive()
    stmt = pg_insert(EtlState).values(key=key, value=value, updated_at=now)
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"],
        set_={"value": value, "updated_at": now},
    )
    await session.execute(stmt)
    await session.commit()


async def get_last_cid(session: AsyncSession) -> int:
    row = await _get(session, _CID_KEY)
    return int(row) if row is not None else 0


async def save_cid(session: AsyncSession, cid: int) -> None:
    await _set(session, _CID_KEY, str(cid))


async def get_completed_step(session: AsyncSession) -> str | None:
    """Return the last successfully completed import step, or None if fresh start."""
    return await _get(session, _STEP_KEY)


async def save_completed_step(session: AsyncSession, step: str) -> None:
    """Mark a step as completed so a resumed import can skip it."""
    await _set(session, _STEP_KEY, step)


async def clear_import_progress(session: AsyncSession) -> None:
    """Reset checkpoint — forces full re-import from scratch."""
    await _set(session, _STEP_KEY, "")


async def get_last_nightly_sync_date(session: AsyncSession) -> str | None:
    """Return ISO date string of last successful nightly sync, or None."""
    return await _get(session, _LAST_SYNC_KEY)


async def save_nightly_sync_date(session: AsyncSession) -> None:
    """Record today as last successful nightly sync date."""
    today = datetime.now(UTC).date().isoformat()
    await _set(session, _LAST_SYNC_KEY, today)


def steps_to_run(last_completed: str | None) -> set[str]:
    """Return set of steps that still need to run given last completed step."""
    if not last_completed or last_completed not in IMPORT_STEPS:
        return set(IMPORT_STEPS)
    idx = IMPORT_STEPS.index(last_completed)
    return set(IMPORT_STEPS[idx + 1 :])
