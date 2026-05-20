"""Bulk upsert loader — INSERT ... ON CONFLICT (rc_code) DO UPDATE in batches.

PostgreSQL limits each statement to 32767 bound parameters, so each batch is
chunked into pieces of ``MAX_PG_PARAMS / fields_per_row`` rows.
"""

import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from etl.config import settings

log = logging.getLogger(__name__)

_MAX_PG_PARAMS = settings.max_pg_params


async def upsert_batch(session: AsyncSession, model: type, rows: list[dict[str, Any]]) -> None:
    """Execute a single batch as one or more INSERT ... ON CONFLICT statements.

    Splits the batch into chunks small enough to fit PostgreSQL's 32767-param limit.
    Raises ``RuntimeError`` on DB error, with the first line of the original message.
    """
    chunk_size = _MAX_PG_PARAMS // len(rows[0])
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        stmt = insert(model).values(chunk)
        provided = set(chunk[0].keys()) - {"rc_code"}
        update_cols = {c.name: c for c in stmt.excluded if c.name in provided}
        stmt = stmt.on_conflict_do_update(index_elements=["rc_code"], set_=update_cols)
        try:
            await session.execute(stmt)
        except Exception as exc:
            first_line = str(exc).splitlines()[0]
            log.error("Upsert failed on %s: %s", model.__tablename__, first_line)
            raise RuntimeError(f"upsert failed on {model.__tablename__}: {first_line}") from None


async def upsert_all(
    session: AsyncSession,
    model: type,
    records: AsyncIterator[dict[str, Any]],
    batch_size: int | None = None,
) -> int:
    """Consume :records: async iterator; upsert rows into :model: table in batches.

    Returns total number of rows upserted.
    Commits after each batch (so partial failures don't lose earlier progress).
    """
    if batch_size is None:
        batch_size = settings.upsert_batch_size

    batch: list[dict[str, Any]] = []
    total = 0
    async for row in records:
        batch.append(row)
        if len(batch) >= batch_size:
            await upsert_batch(session, model, batch)
            await session.commit()
            total += len(batch)
            log.info("  %s: %d rows", model.__tablename__, total)
            batch.clear()

    if batch:
        await upsert_batch(session, model, batch)
        await session.commit()
        total += len(batch)
    return total
