"""Auto-zones: ServiceZone polygons derived from address offerings.

One zone per CONNECTED coverage area per technology (`source='auto'`):
polygon = union of 150 m buffers around addresses holding an `available`
offering, split into connected components (ST_Dump). Rebuilt after every
offering change. Address offerings are the source of truth; auto-zones are
pure visualization and never feed availability.

Identity across rebuilds: each new component is matched to an existing auto
zone of the technology by largest intersection area (greedy). Merge -> the
larger-overlap zone survives (its custom_name with it); split -> the largest
piece inherits the zone id, the rest get fresh rows. Hidden zones
(deleted_at) take part in matching and are revived on match.

Design: docs/superpowers/specs/2026-06-11-coverage-maintenance-model-design.md
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

# Connected coverage components via ST_ClusterDBSCAN (O(n log n)) — groups points
# whose buffers would touch (eps = 2*radius), then unions each cluster separately.
# Much faster than ST_Union-all + ST_Dump which is O(n²) in geometry complexity.
# Order: largest cluster (by point count) first — stable name suffixes.
_COMPONENTS_SQL = text("""
    WITH pts AS (
        SELECT ST_Transform(a.point, 3346) AS p,
               ao.max_download_mbps AS dl,
               ao.max_upload_mbps AS ul,
               l.name AS locality
        FROM addresses a
        JOIN address_offerings ao ON ao.address_code = a.rc_code
        JOIN localities l ON l.rc_code = a.locality_code
        WHERE ao.technology_id = :tid
          AND ao.status = 'available'
          AND a.deleted_at IS NULL
          AND a.point IS NOT NULL
    ),
    clustered AS (
        SELECT p, dl, ul, locality,
               ST_ClusterDBSCAN(p, eps := 2.0 * :radius, minpoints := 1) OVER () AS cid
        FROM pts
    )
    SELECT
        ST_Multi(ST_Transform(
            ST_SimplifyPreserveTopology(ST_Union(ST_Buffer(p, :radius)), 1.0),
            4326)) AS poly,
        ST_AsEWKT(ST_Multi(ST_Transform(
            ST_SimplifyPreserveTopology(ST_Union(ST_Buffer(p, :radius)), 1.0),
            4326))) AS poly_ewkt,
        MAX(dl) AS dl,
        MAX(ul) AS ul,
        mode() WITHIN GROUP (ORDER BY locality) AS locality
    FROM clustered
    GROUP BY cid
    ORDER BY COUNT(*) DESC
""")

# Intersection area between an existing zone and a component (for identity matching;
# units in 4326 degrees are sufficient since we only compare within the same run).
_OVERLAP_SQL = text("""
    SELECT ST_Area(ST_Intersection(z.polygon::geometry, ST_GeomFromEWKT(:comp)))
    FROM service_zones z
    WHERE z.id = CAST(:zid AS uuid)
""")


async def rebuild_auto_zones(
    session: AsyncSession,
    technology_id: uuid.UUID | None = None,
    radius_m: float = AUTO_ZONE_RADIUS_M,
) -> list[str]:
    """Rebuild auto-zones for one technology (or all with offerings).

    Returns effective names of zones rebuilt or hidden.
    """
    if technology_id is not None:
        tech_ids = [technology_id]
    else:
        rows = await session.execute(text("SELECT DISTINCT technology_id FROM address_offerings"))
        tech_ids = [row[0] for row in rows]

    touched: list[str] = []
    for tech_id in tech_ids:
        touched.extend(await _rebuild_for_technology(session, tech_id, radius_m))
    return touched


async def _rebuild_for_technology(
    session: AsyncSession, tech_id: uuid.UUID, radius_m: float
) -> list[str]:
    """Rebuild one technology's auto-zones. Returns touched zone names."""
    # Serialize concurrent rebuilds of the same technology (no duplicate zones).
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('auto_zone:' || :tid))"),
        {"tid": str(tech_id)},
    )

    tech = await session.get(Technology, tech_id)
    if tech is None:
        log.warning("Auto-zone rebuild skipped: technology %s not found", tech_id)
        return []

    comps = (
        await session.execute(_COMPONENTS_SQL, {"tid": str(tech_id), "radius": radius_m})
    ).all()

    # All auto zones of this technology, hidden included — matching a hidden
    # zone revives it, so custom_name survives a temporary outage.
    zones = list(
        (
            await session.execute(
                select(ServiceZone)
                .join(ZoneOffering, ZoneOffering.zone_id == ServiceZone.id)
                .where(ServiceZone.source == "auto", ZoneOffering.technology_id == tech_id)
                .order_by(ServiceZone.created_at)
            )
        ).scalars().all()
    )

    touched: list[str] = []
    current = now()

    if not comps:
        for zone in zones:
            if zone.deleted_at is None:
                zone.deleted_at = current
                touched.append(zone.custom_name or zone.name)
                log.info("Auto zone '%s' hidden (no available offerings)", zone.name)
        await session.flush()
        return touched

    # Pairwise overlap zone x component, greedy largest-overlap matching.
    pairs: list[tuple[float, ServiceZone, int]] = []
    for zone in zones:
        for ci, comp in enumerate(comps):
            overlap = (
                await session.execute(
                    _OVERLAP_SQL, {"zid": str(zone.id), "comp": comp.poly_ewkt}
                )
            ).scalar()
            if overlap and overlap > 0:
                pairs.append((overlap, zone, ci))
    pairs.sort(key=lambda t: t[0], reverse=True)

    comp_zone: dict[int, ServiceZone] = {}
    used_zone_ids: set[uuid.UUID] = set()
    for _, zone, ci in pairs:
        if ci in comp_zone or zone.id in used_zone_ids:
            continue
        comp_zone[ci] = zone
        used_zone_ids.add(zone.id)

    # Components come ordered by area DESC; name collisions get " (2)", " (3)"...
    name_counts: dict[str, int] = {}
    for ci, comp in enumerate(comps):
        base = f"Auto: {tech.display_name} — {comp.locality}"
        name_counts[base] = name_counts.get(base, 0) + 1
        name = base if name_counts[base] == 1 else f"{base} ({name_counts[base]})"

        zone = comp_zone.get(ci)
        if zone is None:
            zone = ServiceZone(
                name=name,
                description="Strefa generowana automatycznie z ofert adresowych",
                polygon=comp.poly,
                source="auto",
                created_by=None,
            )
            session.add(zone)
            comp_zone[ci] = zone
        else:
            zone.polygon = comp.poly
            zone.name = name
            zone.deleted_at = None
        touched.append(zone.custom_name or name)
    await session.flush()

    for ci, comp in enumerate(comps):
        zone = comp_zone[ci]
        offering_stmt = (
            pg_insert(ZoneOffering)
            .values(
                id=uuid.uuid4(),
                zone_id=zone.id,
                technology_id=tech_id,
                status="available",
                max_download_mbps=comp.dl,
                max_upload_mbps=comp.ul,
                status_since=current.date(),
                created_at=current,
                updated_at=current,
            )
            .on_conflict_do_update(
                index_elements=["zone_id", "technology_id"],
                set_={
                    "status": "available",
                    "max_download_mbps": comp.dl,
                    "max_upload_mbps": comp.ul,
                    "updated_at": current,
                },
            )
        )
        await session.execute(offering_stmt)

    for zone in zones:
        if zone.id not in used_zone_ids and zone.deleted_at is None:
            zone.deleted_at = current
            touched.append(zone.custom_name or zone.name)
            log.info("Auto zone '%s' hidden (area merged or gone)", zone.name)

    await session.flush()
    log.info("Auto zones for '%s' rebuilt: %d area(s)", tech.display_name, len(comps))
    return touched


async def rebuild_auto_zones_background(technology_id: uuid.UUID | None = None) -> None:
    """For FastAPI BackgroundTasks: own session, commits, never raises."""
    try:
        async with AsyncSessionLocal() as session:
            await rebuild_auto_zones(session, technology_id)
            await session.commit()
    except Exception:
        log.exception("Auto-zone background rebuild failed (technology_id=%s)", technology_id)
