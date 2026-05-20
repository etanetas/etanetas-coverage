import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.auth import require_role
from app.dependencies import get_db
from app.models.admin import User
from app.models.service import AddressOffering
from app.schemas.admin import (
    AddressDetail,
    AddressOfferingCreate,
    AddressOfferingOut,
    AddressOfferingUpdate,
    AddressSearchRequest,
    AddressSearchResult,
)

router = APIRouter(prefix="/api/v1/admin/addresses", tags=["admin-addresses"])

_MUNI_SHORT = "replace(replace(m.name, ' rajono', ' raj.'), ' miesto', ' m.')"
_LOCALITY_LABEL = f"""
    CASE l.type
        WHEN 'miestas' THEN l.name
        ELSE l.name || COALESCE(' ' || l.type_abbr, '') || ', ' || ({_MUNI_SHORT})
    END
"""
_STREET_WITH_TYPE = "s.name || COALESCE(' ' || s.type_abbr, '')"
_HOUSE = "a.house_no || COALESCE(' k.' || a.corpus_no, '') || COALESCE('-' || a.flat_no, '')"
_FULL_ADDRESS = f"""
    CASE WHEN s.name IS NOT NULL
         THEN ({_STREET_WITH_TYPE}) || ' ' || ({_HOUSE}) || ', ' || ({_LOCALITY_LABEL})
         ELSE ({_HOUSE}) || ', ' || ({_LOCALITY_LABEL})
    END
"""
_ADDR_JOINS = """
    LEFT JOIN streets s ON s.rc_code = a.street_code
    JOIN localities l ON l.rc_code = a.locality_code
    JOIN municipalities m ON m.rc_code = l.muni_code
"""


@router.post("/search", response_model=list[AddressSearchResult])
async def search_addresses(
    body: AddressSearchRequest,
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AddressSearchResult]:
    if len(body.q) < 2:
        return []

    filters = ["a.deleted_at IS NULL"]
    params: dict = {"q": body.q, "limit": body.limit}

    if body.address_type:
        filters.append("a.address_type = :address_type")
        params["address_type"] = body.address_type
    if body.locality_code:
        filters.append("a.locality_code = :locality_code")
        params["locality_code"] = body.locality_code
    if body.street_code:
        filters.append("a.street_code = :street_code")
        params["street_code"] = body.street_code
    if body.has_point:
        filters.append("a.point IS NOT NULL")
    if body.has_offering:
        filters.append(
            "EXISTS (SELECT 1 FROM address_offerings ao WHERE ao.address_code = a.rc_code)"
        )

    where = " AND ".join(filters)
    sql = text(f"""
        SELECT
            a.rc_code,
            {_FULL_ADDRESS} AS full_address,
            a.postal_code,
            a.address_type
        FROM addresses a
        {_ADDR_JOINS}
        WHERE {where}
          AND (
              s.full_name % :q
              OR l.name % :q
              OR l.name_k % :q
              OR (COALESCE(({_STREET_WITH_TYPE}) || ' ', '') || a.house_no || ', ' || l.name) % :q
          )
        ORDER BY similarity(COALESCE(s.full_name, l.name) || ' ' || a.house_no, :q) DESC
        LIMIT :limit
    """)
    rows = (await db.execute(sql, params)).mappings().all()
    return [AddressSearchResult(**r) for r in rows]


@router.get("/{rc_code}", response_model=AddressDetail)
async def get_address(
    rc_code: int,
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AddressDetail:
    sql = text(f"""
        SELECT
            a.rc_code,
            {_FULL_ADDRESS} AS full_address,
            a.postal_code,
            a.address_type,
            l.rc_code AS locality_code,
            l.name AS locality_name,
            s.rc_code AS street_code,
            ({_STREET_WITH_TYPE}) AS street_name,
            a.house_no,
            a.corpus_no,
            a.flat_no,
            ST_X(a.point::geometry) AS lon,
            ST_Y(a.point::geometry) AS lat
        FROM addresses a
        {_ADDR_JOINS}
        WHERE a.rc_code = :rc_code AND a.deleted_at IS NULL
    """)
    row = (await db.execute(sql, {"rc_code": rc_code})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Address not found")
    return AddressDetail(**row)


@router.get("/{rc_code}/offerings", response_model=list[AddressOfferingOut])
async def list_address_offerings(
    rc_code: int,
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AddressOffering]:
    result = await db.execute(
        select(AddressOffering)
        .where(AddressOffering.address_code == rc_code)
        .order_by(AddressOffering.created_at)
    )
    return list(result.scalars().all())


@router.post("/{rc_code}/offerings", response_model=AddressOfferingOut, status_code=201)
async def create_address_offering(
    rc_code: int,
    body: AddressOfferingCreate,
    current_user: Annotated[User, Depends(require_role("editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AddressOffering:
    existing = await db.execute(
        select(AddressOffering).where(
            AddressOffering.address_code == rc_code,
            AddressOffering.technology_id == body.technology_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Offering for this technology already exists")

    offering = AddressOffering(
        address_code=rc_code,
        created_by=current_user.id,
        **body.model_dump(),
    )
    db.add(offering)
    await db.flush()
    await log_action(
        db,
        current_user.id,
        "address_offering",
        str(offering.id),
        "create",
        {"address_code": rc_code, **body.model_dump()},
    )
    await db.commit()
    await db.refresh(offering)
    return offering


@router.put("/offerings/{offering_id}", response_model=AddressOfferingOut)
async def update_address_offering(
    offering_id: uuid.UUID,
    body: AddressOfferingUpdate,
    current_user: Annotated[User, Depends(require_role("editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AddressOffering:
    offering = await _require_offering(db, offering_id)

    changes = body.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(offering, field, value)
    offering.updated_at = datetime.now()

    await log_action(
        db,
        current_user.id,
        "address_offering",
        str(offering_id),
        "update",
        {"address_code": offering.address_code, **changes},
    )
    await db.commit()
    await db.refresh(offering)
    return offering


@router.delete("/offerings/{offering_id}", status_code=204)
async def delete_address_offering(
    offering_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role("editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    offering = await _require_offering(db, offering_id)
    address_code = offering.address_code
    await db.delete(offering)
    await log_action(
        db,
        current_user.id,
        "address_offering",
        str(offering_id),
        "delete",
        {"address_code": address_code},
    )
    await db.commit()


async def _require_offering(db: AsyncSession, offering_id: uuid.UUID) -> AddressOffering:
    result = await db.execute(select(AddressOffering).where(AddressOffering.id == offering_id))
    offering = result.scalar_one_or_none()
    if offering is None:
        raise HTTPException(status_code=404, detail="Offering not found")
    return offering
