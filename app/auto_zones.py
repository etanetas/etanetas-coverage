"""Auto-zones: ServiceZone polygons derived from address offerings.

One zone per technology (`source='auto'`), polygon = union of buffers around
addresses holding an `available` offering. Rebuilt after every offering
change. Address offerings are the source of truth; auto-zones are pure
visualization.

Design: docs/superpowers/specs/2026-06-11-auto-zones-design.md
"""

import logging
import uuid

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.service import ServiceZone, ZoneOffering
from app.models.technology import Technology
from app.time import now

log = logging.getLogger(__name__)

AUTO_ZONE_RADIUS_M = 150.0


async def rebuild_auto_zones(
    session: AsyncSession,
    technology_id: uuid.UUID | None = None,
    radius_m: float = AUTO_ZONE_RADIUS_M,
) -> list[str]:
    """Rebuild auto-zones for one technology (or all with offerings).

    Returns names of zones rebuilt or hidden.
    """
    if technology_id is not None:
        tech_ids = [technology_id]
    else:
        rows = await session.execute(text("SELECT DISTINCT technology_id FROM address_offerings"))
        tech_ids = [row[0] for row in rows]

    rebuilt: list[str] = []
    for tech_id in tech_ids:
        name = await _rebuild_for_technology(session, tech_id, radius_m)
        if name is not None:
            rebuilt.append(name)
    return rebuilt


async def _rebuild_for_technology(
    session: AsyncSession, tech_id: uuid.UUID, radius_m: float
) -> str | None:
    """Rebuild one technology's auto-zone. Returns the zone name, or None if no-op."""
    # Serialize concurrent rebuilds of the same technology (no duplicate zones).
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('auto_zone:' || :tid))"),
        {"tid": str(tech_id)},
    )

    tech = await session.get(Technology, tech_id)
    if tech is None:
        log.warning("Auto-zone rebuild skipped: technology %s not found", tech_id)
        return None

    row = (
        await session.execute(
            text(
                """
                SELECT ST_Multi(ST_Transform(
                         ST_SimplifyPreserveTopology(
                           ST_Union(ST_Buffer(ST_Transform(a.point, 3346), :radius)), 1.0),
                         4326)) AS poly,
                       MAX(ao.max_download_mbps) AS dl,
                       MAX(ao.max_upload_mbps) AS ul
                FROM addresses a
                JOIN address_offerings ao ON ao.address_code = a.rc_code
                WHERE ao.technology_id = :tid
                  AND ao.status = 'available'
                  AND a.deleted_at IS NULL
                  AND a.point IS NOT NULL
                """
            ),
            {"radius": radius_m, "tid": str(tech_id)},
        )
    ).one()

    # Auto zone lookup ignores deleted_at: a hidden zone is revived on rebuild.
    zone = (
        await session.execute(
            select(ServiceZone)
            .join(ZoneOffering, ZoneOffering.zone_id == ServiceZone.id)
            .where(ServiceZone.source == "auto", ZoneOffering.technology_id == tech_id)
            .order_by(ServiceZone.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()

    if row.poly is None:
        if zone is not None and zone.deleted_at is None:
            zone.deleted_at = now()
            await session.flush()
            log.info("Auto zone '%s' hidden (no available offerings)", zone.name)
            return zone.name
        return None

    name = f"Auto: {tech.display_name}"
    if zone is None:
        zone = ServiceZone(
            name=name,
            description="Strefa generowana automatycznie z ofert adresowych",
            polygon=row.poly,
            source="auto",
            created_by=None,
        )
        session.add(zone)
    else:
        zone.polygon = row.poly
        zone.name = name
        zone.deleted_at = None
    await session.flush()

    current = now()
    offering_stmt = (
        pg_insert(ZoneOffering)
        .values(
            id=uuid.uuid4(),
            zone_id=zone.id,
            technology_id=tech_id,
            status="available",
            max_download_mbps=row.dl,
            max_upload_mbps=row.ul,
            status_since=current.date(),
            created_at=current,
            updated_at=current,
        )
        .on_conflict_do_update(
            index_elements=["zone_id", "technology_id"],
            set_={
                "status": "available",
                "max_download_mbps": row.dl,
                "max_upload_mbps": row.ul,
                "updated_at": current,
            },
        )
    )
    await session.execute(offering_stmt)
    log.info("Auto zone '%s' rebuilt", name)
    return name


async def rebuild_auto_zones_background(technology_id: uuid.UUID | None = None) -> None:
    """For FastAPI BackgroundTasks: own session, commits, never raises."""
    try:
        async with AsyncSessionLocal() as session:
            await rebuild_auto_zones(session, technology_id)
            await session.commit()
    except Exception:
        log.exception("Auto-zone background rebuild failed (technology_id=%s)", technology_id)
