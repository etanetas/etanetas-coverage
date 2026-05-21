"""Coverage statistics endpoint — dashboard metrics."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.dependencies import get_db
from app.models.admin import User

router = APIRouter(prefix="/api/v1/admin/coverage", tags=["admin-stats"])


class StatusBreakdown(BaseModel):
    status: str
    count: int


class UncoveredLocality(BaseModel):
    locality_code: int
    locality_name: str
    municipality: str
    uncovered_count: int


class CoverageStats(BaseModel):
    total_buildings: int
    covered_buildings: int  # buildings with at least one offering (zone or address-specific)
    address_offerings_count: int  # specific address overrides
    zones_count: int
    zones_with_polygon: int
    zone_offerings_count: int
    addresses_by_status: list[StatusBreakdown]
    top_uncovered_localities: list[UncoveredLocality]


@router.get("/stats", response_model=CoverageStats)
async def get_coverage_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    top_uncovered: int = Query(10, ge=1, le=50),
) -> CoverageStats:
    """High-level coverage metrics for dashboard."""

    total_buildings = await db.scalar(text("""
        SELECT COUNT(*) FROM addresses
        WHERE address_type = 'building' AND deleted_at IS NULL
    """)) or 0

    # Buildings covered = buildings with address_offering OR inside any zone with offering
    covered = await db.scalar(text("""
        SELECT COUNT(DISTINCT a.rc_code)
        FROM addresses a
        WHERE a.address_type = 'building'
          AND a.deleted_at IS NULL
          AND a.point IS NOT NULL
          AND (
            EXISTS(SELECT 1 FROM address_offerings ao WHERE ao.address_code = a.rc_code)
            OR EXISTS(
              SELECT 1 FROM service_zones z
              JOIN zone_offerings zo ON zo.zone_id = z.id
              WHERE z.polygon IS NOT NULL
                AND ST_Contains(z.polygon::geometry, a.point::geometry)
                AND zo.status IN ('available', 'planned')
            )
          )
    """)) or 0

    address_offerings = await db.scalar(text("SELECT COUNT(*) FROM address_offerings")) or 0
    zones_total = await db.scalar(text("SELECT COUNT(*) FROM service_zones")) or 0
    zones_with_polygon = await db.scalar(text(
        "SELECT COUNT(*) FROM service_zones WHERE polygon IS NOT NULL"
    )) or 0
    zone_offerings = await db.scalar(text("SELECT COUNT(*) FROM zone_offerings")) or 0

    # Status breakdown across both sources (each address counted once per status)
    status_rows = (await db.execute(text("""
        SELECT status, COUNT(*) AS count FROM (
            SELECT status FROM address_offerings
            UNION ALL
            SELECT status FROM zone_offerings
        ) combined
        GROUP BY status ORDER BY count DESC
    """))).mappings().all()

    # Top localities with most uncovered buildings (where ST_Contains zone)
    uncov_rows = (await db.execute(text("""
        SELECT
            l.rc_code AS locality_code,
            l.name AS locality_name,
            m.name AS municipality,
            COUNT(*) AS uncovered_count
        FROM addresses a
        JOIN localities l ON l.rc_code = a.locality_code
        JOIN municipalities m ON m.rc_code = l.muni_code
        WHERE a.address_type = 'building'
          AND a.deleted_at IS NULL
          AND a.point IS NOT NULL
          AND NOT EXISTS(SELECT 1 FROM address_offerings ao WHERE ao.address_code = a.rc_code)
          AND NOT EXISTS(
            SELECT 1 FROM service_zones z
            JOIN zone_offerings zo ON zo.zone_id = z.id
            WHERE z.polygon IS NOT NULL
              AND ST_Contains(z.polygon::geometry, a.point::geometry)
              AND zo.status IN ('available', 'planned')
          )
        GROUP BY l.rc_code, l.name, m.name
        ORDER BY uncovered_count DESC
        LIMIT :limit
    """), {"limit": top_uncovered})).mappings().all()

    return CoverageStats(
        total_buildings=int(total_buildings),
        covered_buildings=int(covered),
        address_offerings_count=int(address_offerings),
        zones_count=int(zones_total),
        zones_with_polygon=int(zones_with_polygon),
        zone_offerings_count=int(zone_offerings),
        addresses_by_status=[StatusBreakdown(**r) for r in status_rows],
        top_uncovered_localities=[UncoveredLocality(**r) for r in uncov_rows],
    )
