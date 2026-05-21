"""Coverage statistics endpoint — dashboard metrics."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.dependencies import get_db
from app.models.admin import User
from app.schemas.admin import CoverageStats, StatusBreakdown, UncoveredLocality

router = APIRouter(prefix="/api/v1/admin/coverage", tags=["admin-stats"])

StatsScope = Literal["operational", "all"]


async def _resolve_muni_codes(
    db: AsyncSession,
    *,
    scope: StatsScope,
    muni_codes: list[int] | None,
) -> tuple[list[int] | None, list[str], str]:
    if scope == "all":
        return None, [], "All Lithuania"

    if muni_codes:
        codes_to_resolve = muni_codes
    else:
        codes_to_resolve = settings.stats_municipality_codes

    rows = (
        await db.execute(
            text("SELECT rc_code, name FROM municipalities WHERE rc_code = ANY(:codes) ORDER BY name"),
            {"codes": codes_to_resolve},
        )
    ).mappings().all()

    if not rows and not muni_codes:
        rows = (
            await db.execute(
                text("SELECT rc_code, name FROM municipalities WHERE name = ANY(:names) ORDER BY name"),
                {"names": settings.stats_municipality_names},
            )
        ).mappings().all()

    if not rows:
        if muni_codes:
            raise HTTPException(status_code=400, detail="No municipalities found for the given codes")
        raise HTTPException(
            status_code=500,
            detail="Operational area not configured — no matching municipalities found",
        )
    names = [str(row["name"]) for row in rows]
    codes = [int(row["rc_code"]) for row in rows]
    label = "Selected municipalities" if muni_codes else "Operational area"
    return codes, names, label


def _scoped_address_filter(muni_codes: list[int] | None) -> tuple[str, dict]:
    if muni_codes is None:
        return "", {}
    return (
        """
          AND EXISTS (
            SELECT 1 FROM localities l
            WHERE l.rc_code = a.locality_code
              AND l.muni_code = ANY(:muni_codes)
          )
        """,
        {"muni_codes": muni_codes},
    )


@router.get("/stats", response_model=CoverageStats)
async def get_coverage_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    scope: StatsScope = Query("operational"),
    muni_codes: list[int] | None = Query(None),
    top_uncovered: int = Query(10, ge=1, le=50),
) -> CoverageStats:
    """High-level coverage metrics for dashboard."""

    resolved_codes, municipality_names, scope_label = await _resolve_muni_codes(
        db,
        scope=scope,
        muni_codes=muni_codes,
    )
    address_filter, address_params = _scoped_address_filter(resolved_codes)

    total_buildings = await db.scalar(
        text(f"""
        SELECT COUNT(*) FROM addresses a
        WHERE a.address_type = 'building'
          AND a.deleted_at IS NULL
          {address_filter}
    """),
        address_params,
    ) or 0

    covered = await db.scalar(
        text(f"""
        SELECT COUNT(DISTINCT a.rc_code)
        FROM addresses a
        WHERE a.address_type = 'building'
          AND a.deleted_at IS NULL
          AND a.point IS NOT NULL
          {address_filter}
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
    """),
        address_params,
    ) or 0

    if resolved_codes is None:
        address_offerings = await db.scalar(text("SELECT COUNT(*) FROM address_offerings")) or 0
    else:
        address_offerings = await db.scalar(
            text("""
            SELECT COUNT(*)
            FROM address_offerings ao
            JOIN addresses a ON a.rc_code = ao.address_code
            WHERE a.address_type = 'building'
              AND a.deleted_at IS NULL
              AND EXISTS (
                SELECT 1 FROM localities l
                WHERE l.rc_code = a.locality_code
                  AND l.muni_code = ANY(:muni_codes)
              )
        """),
            address_params,
        ) or 0

    zones_total = await db.scalar(text("SELECT COUNT(*) FROM service_zones")) or 0
    zones_with_polygon = await db.scalar(
        text("SELECT COUNT(*) FROM service_zones WHERE polygon IS NOT NULL")
    ) or 0
    zone_offerings = await db.scalar(text("SELECT COUNT(*) FROM zone_offerings")) or 0

    if resolved_codes is None:
        status_rows = (
            await db.execute(
                text("""
            SELECT status, COUNT(*) AS count FROM (
                SELECT status FROM address_offerings
                UNION ALL
                SELECT status FROM zone_offerings
            ) combined
            GROUP BY status ORDER BY count DESC
        """)
            )
        ).mappings().all()
    else:
        status_rows = (
            await db.execute(
                text("""
            SELECT status, COUNT(*) AS count
            FROM address_offerings ao
            JOIN addresses a ON a.rc_code = ao.address_code
            WHERE a.address_type = 'building'
              AND a.deleted_at IS NULL
              AND EXISTS (
                SELECT 1 FROM localities l
                WHERE l.rc_code = a.locality_code
                  AND l.muni_code = ANY(:muni_codes)
              )
            GROUP BY status
            ORDER BY count DESC
        """),
                address_params,
            )
        ).mappings().all()

    uncov_rows = (
        await db.execute(
            text(f"""
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
          {address_filter}
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
    """),
            {**address_params, "limit": top_uncovered},
        )
    ).mappings().all()

    return CoverageStats(
        total_buildings=int(total_buildings),
        covered_buildings=int(covered),
        address_offerings_count=int(address_offerings),
        zones_count=int(zones_total),
        zones_with_polygon=int(zones_with_polygon),
        zone_offerings_count=int(zone_offerings),
        addresses_by_status=[StatusBreakdown(**r) for r in status_rows],
        top_uncovered_localities=[UncoveredLocality(**r) for r in uncov_rows],
        scope=scope,
        scope_label=scope_label,
        scope_municipalities=municipality_names,
    )
