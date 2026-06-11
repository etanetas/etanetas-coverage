import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.address_labels import (  # noqa: F401
    _ADDR_JOINS,
    _FULL_ADDRESS,
    _HOUSE,
    _LOCALITY_LABEL,
    _MUNI_SHORT,
    _STREET_WITH_TYPE,
)
from app.dependencies import get_db
from app.limiter import limiter
from app.schemas.public import (
    AddressInfo,
    AddressSearchResult,
    AvailabilityResponse,
    PublicAddressSearchResponse,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/public/addresses", tags=["public"])

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

# Dostepnosc liczy sie WYLACZNIE z ofert adresowych. Strefy (w tym auto-zony
# generowane z tych samych ofert) sa czysta wizualizacja — patrz spec
# docs/superpowers/specs/2026-06-11-coverage-maintenance-model-design.md
_AVAILABILITY_SQL = text("""
    SELECT
        tt.public_name            AS technology,
        MAX(ao.max_download_mbps) AS max_dl_mbps,
        MAX(ao.max_upload_mbps)   AS max_ul_mbps,
        ao.status,
        MIN(ao.planned_until)     AS planned_until
    FROM address_offerings ao
    JOIN technologies t ON t.id = ao.technology_id
    JOIN technology_types tt ON tt.id = t.type_id
    WHERE ao.address_code = :rc_code
      AND ao.status IN ('available', 'planned')
      AND tt.deleted_at IS NULL
      AND t.deleted_at IS NULL
    GROUP BY tt.id, tt.public_name, tt.sort_order, ao.status
    ORDER BY tt.sort_order
""")


@router.get("/search", response_model=PublicAddressSearchResponse, summary="Search addresses", operation_id="public.addresses.search")
@limiter.limit("60/minute")
async def search_addresses(
    request: Request,
    q: Annotated[str, Query(min_length=2, max_length=100, description="Address search query")],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublicAddressSearchResponse:
    rows = (await db.execute(_SEARCH_SQL, {"q": q})).mappings().all()
    return PublicAddressSearchResponse(items=[AddressSearchResult(**row) for row in rows])


@router.get("/{rc_code}/availability", response_model=AvailabilityResponse, summary="Address availability", operation_id="public.addresses.availability")
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
            available.append(
                {
                    "technology": row["technology"],
                    "max_dl_mbps": row["max_dl_mbps"],
                    "max_ul_mbps": row["max_ul_mbps"],
                }
            )
        else:
            planned.append({"technology": row["technology"], "planned_until": row["planned_until"]})

    return AvailabilityResponse(
        address=AddressInfo(**addr_row),
        available=available,
        planned=planned,
    )
