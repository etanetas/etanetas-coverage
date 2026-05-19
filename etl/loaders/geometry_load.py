import logging
from collections.abc import Iterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

_BATCH_SIZE = 1000

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
    rows: Iterator[dict[str, Any]],
) -> int:
    stmt = _UPDATE_SQL[table]
    batch: list[dict[str, Any]] = []
    total = 0

    for row in rows:
        batch.append(row)
        if len(batch) >= _BATCH_SIZE:
            await session.execute(stmt, batch)
            await session.commit()
            total += len(batch)
            log.info("  %s geometry: %d rows", table, total)
            batch.clear()

    if batch:
        await session.execute(stmt, batch)
        await session.commit()
        total += len(batch)

    return total
