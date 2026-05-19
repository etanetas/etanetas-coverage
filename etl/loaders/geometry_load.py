import logging
from collections.abc import Iterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from etl.config import settings

log = logging.getLogger(__name__)

_BATCH_SIZE = settings.geometry_batch_size

# ST_Multi ensures LineString→MultiLineString and Polygon→MultiPolygon
# ST_Transform converts LKS-94 (EPSG:3346) → WGS84 (EPSG:4326)
_UPDATE_SQL = {
    "localities": text(
        "UPDATE localities SET boundary = ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(:geom), 3346), 4326)), "
        "synced_at = NOW() WHERE rc_code = :rc_code"
    ),
    "streets": text(
        "UPDATE streets SET axis = ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(:geom), 3346), 4326)), "
        "synced_at = NOW() WHERE rc_code = :rc_code"
    ),
}


async def update_geometries(
    session: AsyncSession,
    table: str,
    rows: Iterator[dict[str, Any] | None],
) -> int:
    """Apply geometry UPDATE in batches. ``None`` rows are skipped silently.

    Raises ``KeyError`` if :table: is not in ``_UPDATE_SQL`` (programmer error).
    """
    if table not in _UPDATE_SQL:
        raise KeyError(f"unknown geometry table: {table}")
    stmt = _UPDATE_SQL[table]
    batch: list[dict[str, Any]] = []
    total = 0

    for row in rows:
        if row is None:  # mapper rejected this row (logged WARNING already)
            continue
        batch.append(row)
        if len(batch) >= _BATCH_SIZE:
            try:
                await session.execute(stmt, batch)
                await session.commit()
            except Exception as exc:
                log.error("Geometry batch UPDATE on %s failed: %s", table, exc)
                raise
            total += len(batch)
            log.info("  %s geometry: %d rows", table, total)
            batch.clear()

    if batch:
        try:
            await session.execute(stmt, batch)
            await session.commit()
        except Exception as exc:
            log.error("Final geometry batch UPDATE on %s failed: %s", table, exc)
            raise
        total += len(batch)

    return total
