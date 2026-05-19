import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

_MAX_PG_PARAMS = 32767


async def upsert_batch(session: AsyncSession, model: type, rows: list[dict[str, Any]]) -> None:
    chunk_size = _MAX_PG_PARAMS // len(rows[0])
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        stmt = insert(model).values(chunk)
        provided = set(chunk[0].keys()) - {"rc_code"}
        update_cols = {c.name: c for c in stmt.excluded if c.name in provided}
        stmt = stmt.on_conflict_do_update(index_elements=["rc_code"], set_=update_cols)
        try:
            await session.execute(stmt)
        except Exception as e:
            first_line = str(e).splitlines()[0]
            raise RuntimeError(f"upsert failed on {model.__tablename__}: {first_line}") from None


async def upsert_all(
    session: AsyncSession,
    model: type,
    records: AsyncIterator[dict[str, Any]],
    batch_size: int = 10_000,
) -> int:
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
