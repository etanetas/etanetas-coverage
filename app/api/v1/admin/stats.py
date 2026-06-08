"""Coverage statistics endpoint — dashboard metrics."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.dependencies import get_db
from app.errors import raise_error
from app.models.admin import User
from app.schemas.admin import CoverageStats, StatusBreakdown, UncoveredLocality

router = APIRouter(prefix="/api/v1/admin/coverage", tags=["admin-stats"])

StatsScope = Literal["operational", "all"]


async def _resolve_scope(
    db: AsyncSession,
    *,
    scope: StatsScope,
    muni_codes: list[int] | None,
) -> tuple[str, dict, list[str], str]:
    """Return (address_filter_sql, params, display_names, scope_label).

    address_filter_sql is appended to WHERE clauses where 'addresses a' is present.
    Returns ("", {}, [], label) for scope="all".
    """
    if scope == "all":
        return "", {}, [], "All Lithuania"

    # Manual municipality override via query param
    if muni_codes:
        rows = (
            await db.execute(
                text("SELECT rc_code, name FROM municipalities WHERE rc_code = ANY(:codes) ORDER BY name"),
                {"codes": muni_codes},
            )
        ).mappings().all()
        if not rows:
            raise HTTPException(status_code=400, detail="No municipalities found for the given codes")
        names = [str(row["name"]) for row in rows]
        codes = [int(row["rc_code"]) for row in rows]
        return (
            """
            AND EXISTS (
                SELECT 1 FROM localities l
                WHERE l.rc_code = a.locality_code
                  AND l.muni_code = ANY(:muni_codes)
            )
            """,
            {"muni_codes": codes},
            names,
            "Selected municipalities",
        )

    # Locality-scoped operational area (preferred when configured)
    if settings.stats_locality_codes or settings.stats_locality_names:
        rows = []
        if settings.stats_locality_codes:
            rows = (
                await db.execute(
                    text("SELECT rc_code, name FROM localities WHERE rc_code = ANY(:codes) ORDER BY name"),
                    {"codes": settings.stats_locality_codes},
                )
            ).mappings().all()
        if not rows:
            rows = (
                await db.execute(
                    text("SELECT rc_code, name FROM localities WHERE name = ANY(:names) ORDER BY name"),
                    {"names": settings.stats_locality_names},
                )
            ).mappings().all()
        if not rows:
            raise_error(503, "SERVICE_UNAVAILABLE", "Operational area not configured")
        names = [str(row["name"]) for row in rows]
        codes = [int(row["rc_code"]) for row in rows]
        return "AND a.locality_code = ANY(:locality_codes)", {"locality_codes": codes}, names, "Operational area"

    # Municipality-scoped operational area (legacy fallback)
    rows = (
        await db.execute(
            text("SELECT rc_code, name FROM municipalities WHERE rc_code = ANY(:codes) ORDER BY name"),
            {"codes": settings.stats_municipality_codes},
        )
    ).mappings().all()
    if not rows:
        rows = (
            await db.execute(
                text("SELECT rc_code, name FROM municipalities WHERE name = ANY(:names) ORDER BY name"),
                {"names": settings.stats_municipality_names},
            )
        ).mappings().all()
    if not rows:
        raise_error(503, "SERVICE_UNAVAILABLE", "Operational area not configured")
    names = [str(row["name"]) for row in rows]
    codes = [int(row["rc_code"]) for row in rows]
    return (
        """
        AND EXISTS (
            SELECT 1 FROM localities l
            WHERE l.rc_code = a.locality_code
              AND l.muni_code = ANY(:muni_codes)
        )
        """,
        {"muni_codes": codes},
        names,
        "Operational area",
    )


@router.get("/stats", response_model=CoverageStats, summary="Coverage statistics", operation_id="admin.stats.coverage")
async def get_coverage_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    scope: StatsScope = Query("operational"),
    muni_codes: list[int] | None = Query(None),
    top_uncovered: int = Query(10, ge=1, le=50),
) -> CoverageStats:
    """High-level coverage metrics for dashboard."""

    address_filter, address_params, scope_names, scope_label = await _resolve_scope(
        db, scope=scope, muni_codes=muni_codes
    )

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
                AND z.deleted_at IS NULL
                AND ST_Contains(z.polygon::geometry, a.point::geometry)
                AND zo.status IN ('available', 'planned')
            )
          )
    """),
        address_params,
    ) or 0

    if scope == "all":
        address_offerings = await db.scalar(text("SELECT COUNT(*) FROM address_offerings")) or 0
    else:
        address_offerings = await db.scalar(
            text(f"""
            SELECT COUNT(*)
            FROM address_offerings ao
            JOIN addresses a ON a.rc_code = ao.address_code
            WHERE a.address_type = 'building'
              AND a.deleted_at IS NULL
              {address_filter}
        """),
            address_params,
        ) or 0

    zones_total = await db.scalar(text("SELECT COUNT(*) FROM service_zones WHERE deleted_at IS NULL")) or 0
    zones_with_polygon = await db.scalar(
        text("SELECT COUNT(*) FROM service_zones WHERE polygon IS NOT NULL AND deleted_at IS NULL")
    ) or 0
    zone_offerings = await db.scalar(text("""
        SELECT COUNT(*) FROM zone_offerings zo
        JOIN service_zones z ON z.id = zo.zone_id
        WHERE z.deleted_at IS NULL
    """)) or 0

    if scope == "all":
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
                text(f"""
            SELECT status, COUNT(*) AS count
            FROM address_offerings ao
            JOIN addresses a ON a.rc_code = ao.address_code
            WHERE a.address_type = 'building'
              AND a.deleted_at IS NULL
              {address_filter}
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
              AND z.deleted_at IS NULL
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
        scope_municipalities=scope_names,
    )
