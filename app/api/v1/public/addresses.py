import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.limiter import limiter
from app.schemas.public import AddressInfo, AddressSearchResult, AvailabilityResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/public/addresses", tags=["public"])

_MUNI_SHORT = "replace(replace(m.name, ' rajono', ' raj.'), ' miesto', ' m.')"

_LOCALITY_LABEL = f"""
    CASE l.type
        WHEN 'miestas' THEN l.name
        ELSE l.name || COALESCE(' ' || l.type_abbr, '') || ', ' || ({_MUNI_SHORT})
    END
"""

_STREET_WITH_TYPE = "s.name || COALESCE(' ' || s.type_abbr, '')"

_ADDR_JOINS = """
    LEFT JOIN streets s ON s.rc_code = a.street_code
    JOIN localities l ON l.rc_code = a.locality_code
    JOIN municipalities m ON m.rc_code = l.muni_code
"""

_HOUSE = "a.house_no || COALESCE(' k.' || a.corpus_no, '')"

_FULL_ADDRESS = f"""
    CASE WHEN s.name IS NOT NULL
         THEN ({_STREET_WITH_TYPE}) || ' ' || ({_HOUSE}) || ', ' || ({_LOCALITY_LABEL})
         ELSE ({_HOUSE}) || ', ' || ({_LOCALITY_LABEL})
    END
"""

_SEARCH_SQL = text(f"""
    SELECT
        a.rc_code,
        {_FULL_ADDRESS} AS full_address,
        a.postal_code
    FROM addresses a
    {_ADDR_JOINS}
    WHERE a.deleted_at IS NULL
      AND a.address_type = 'building'
      AND (
          s.full_name % :q
          OR l.name % :q
          OR l.name_k % :q
          OR m.name % :q
          OR (COALESCE(({_STREET_WITH_TYPE}) || ' ', '') || a.house_no || ', ' || l.name) % :q
      )
    ORDER BY similarity(COALESCE(s.full_name, l.name) || ' ' || a.house_no, :q) DESC
    LIMIT 10
""")

_ADDR_INFO_SQL = text(f"""
    SELECT
        a.rc_code,
        {_FULL_ADDRESS} AS full_address,
        a.postal_code
    FROM addresses a
    {_ADDR_JOINS}
    WHERE a.rc_code = :rc_code AND a.deleted_at IS NULL
""")

_AVAILABILITY_SQL = text("""
    WITH addr AS (
        SELECT rc_code, point FROM addresses WHERE rc_code = :rc_code
    ),
    addr_offerings AS (
        SELECT
            ao.technology_id,
            ao.status,
            ao.max_download_mbps,
            ao.max_upload_mbps,
            ao.planned_until
        FROM address_offerings ao
        WHERE ao.address_code = :rc_code
    ),
    zone_offerings_filtered AS (
        SELECT DISTINCT ON (zo.technology_id)
            zo.technology_id,
            zo.status,
            zo.max_download_mbps,
            zo.max_upload_mbps,
            zo.planned_until
        FROM zone_offerings zo
        JOIN service_zones sz ON sz.id = zo.zone_id
        JOIN addr a ON ST_Contains(sz.polygon, a.point)
        WHERE zo.technology_id NOT IN (SELECT technology_id FROM addr_offerings)
        ORDER BY zo.technology_id, sz.priority DESC
    ),
    combined AS (
        SELECT * FROM addr_offerings
        UNION ALL
        SELECT * FROM zone_offerings_filtered
    )
    SELECT
        tt.public_name         AS technology,
        MAX(c.max_download_mbps) AS max_dl_mbps,
        MAX(c.max_upload_mbps)   AS max_ul_mbps,
        c.status,
        MIN(c.planned_until)     AS planned_until
    FROM combined c
    JOIN technologies t ON t.id = c.technology_id
    JOIN technology_types tt ON tt.id = t.type_id
    WHERE c.status IN ('available', 'planned')
      AND tt.active = TRUE
      AND t.active = TRUE
    GROUP BY tt.id, tt.public_name, tt.sort_order, c.status
    ORDER BY tt.sort_order
""")


@router.get("/search", response_model=list[AddressSearchResult])
@limiter.limit("60/minute")
async def search_addresses(
    request: Request,
    q: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AddressSearchResult]:
    if len(q) < 2:
        return []
    rows = (await db.execute(_SEARCH_SQL, {"q": q})).mappings().all()
    return [AddressSearchResult(**row) for row in rows]


@router.get("/{rc_code}/availability", response_model=AvailabilityResponse)
@limiter.limit("60/minute")
async def get_availability(
    request: Request,
    rc_code: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AvailabilityResponse:
    addr_row = (await db.execute(_ADDR_INFO_SQL, {"rc_code": rc_code})).mappings().first()
    if addr_row is None:
        raise HTTPException(status_code=404, detail="Address not found")

    rows = (await db.execute(_AVAILABILITY_SQL, {"rc_code": rc_code})).mappings().all()

    available = []
    planned = []
    for row in rows:
        if row["status"] == "available":
            available.append({"technology": row["technology"], "max_dl_mbps": row["max_dl_mbps"], "max_ul_mbps": row["max_ul_mbps"]})
        else:
            planned.append({"technology": row["technology"], "planned_until": row["planned_until"]})

    return AvailabilityResponse(
        address=AddressInfo(**addr_row),
        available=available,
        planned=planned,
    )
