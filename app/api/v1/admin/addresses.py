import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import Page, PaginationParams, pagination_params
from app.api.responses import created
from app.audit import log_action
from app.auth import require_role
from app.db.address_labels import _ADDR_JOINS, _FULL_ADDRESS, _HOUSE, _LOCALITY_LABEL, _MUNI_SHORT, _STREET_WITH_TYPE  # noqa: F401
from app.dependencies import get_db
from app.models.address import Address
from app.models.admin import User
from app.models.service import AddressOffering
from app.schemas.admin import (
    AddressDetail,
    AddressOfferingCreate,
    AddressOfferingOut,
    AddressOfferingUpdate,
    AddressSearchResult,
    ZoneOfferingOut,
)
from app.time import now

router = APIRouter(prefix="/api/v1/admin/addresses", tags=["admin-addresses"])


@router.get("", response_model=Page[AddressSearchResult], summary="List addresses", operation_id="admin.addresses.list")
async def list_addresses(
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[PaginationParams, Depends(pagination_params)],
    q: Annotated[str | None, Query(description="fuzzy match on street/locality/full address (min 2 chars)")] = None,
    locality_code: Annotated[int | None, Query()] = None,
    street_code: Annotated[int | None, Query()] = None,
    address_type: Annotated[Literal["building", "premises"] | None, Query()] = None,
    has_point: Annotated[bool, Query()] = False,
    has_offering: Annotated[bool, Query()] = False,
) -> Page[AddressSearchResult]:
    use_fuzzy = q is not None and len(q) >= 2

    filters = ["a.deleted_at IS NULL"]
    params: dict = {}

    if address_type:
        filters.append("a.address_type = :address_type")
        params["address_type"] = address_type
    if locality_code:
        filters.append("a.locality_code = :locality_code")
        params["locality_code"] = locality_code
    if street_code:
        filters.append("a.street_code = :street_code")
        params["street_code"] = street_code
    if has_point:
        filters.append("a.point IS NOT NULL")
    if has_offering:
        filters.append(
            "("
            "EXISTS (SELECT 1 FROM address_offerings ao WHERE ao.address_code = a.rc_code)"
            " OR EXISTS ("
            "    SELECT 1 FROM service_zones sz"
            "    JOIN zone_offerings zo ON zo.zone_id = sz.id"
            "    WHERE sz.polygon IS NOT NULL AND a.point IS NOT NULL"
            "      AND ST_Contains(sz.polygon::geometry, a.point::geometry)"
            ")"
            ")"
        )

    if use_fuzzy:
        params["q"] = q
        filters.append(
            "("
            "s.full_name % :q"
            " OR l.name % :q"
            " OR l.name_k % :q"
            f" OR (COALESCE(({_STREET_WITH_TYPE}) || ' ', '') || a.house_no || ', ' || l.name) % :q"
            ")"
        )
        order_by = "similarity(COALESCE(s.full_name, l.name) || ' ' || a.house_no, :q) DESC"
    else:
        order_by = "a.rc_code"

    where = " AND ".join(filters)

    count_sql = text(f"""
        SELECT COUNT(*) FROM addresses a
        {_ADDR_JOINS}
        WHERE {where}
    """)
    total = int((await db.execute(count_sql, params)).scalar() or 0)

    params["limit"] = page.limit
    params["offset"] = page.offset
    sql = text(f"""
        SELECT
            a.rc_code,
            {_FULL_ADDRESS} AS full_address,
            a.postal_code,
            a.address_type
        FROM addresses a
        {_ADDR_JOINS}
        WHERE {where}
        ORDER BY {order_by}
        LIMIT :limit OFFSET :offset
    """)
    rows = (await db.execute(sql, params)).mappings().all()
    return Page[AddressSearchResult](
        total=total,
        items=[AddressSearchResult(**r) for r in rows],
    )


@router.get("/{rc_code}", response_model=AddressDetail, summary="Get address detail", operation_id="admin.addresses.get")
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


class ZoneCoverageItem(BaseModel):
    zone_id: uuid.UUID
    zone_name: str
    zone_priority: int
    offerings: list[ZoneOfferingOut]


@router.get("/{rc_code}/zone-coverage", response_model=Page[ZoneCoverageItem], summary="List zone coverage for address", operation_id="admin.addresses.zone-coverage.list")
async def get_address_zone_coverage(
    rc_code: int,
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[PaginationParams, Depends(pagination_params)],
) -> Page[ZoneCoverageItem]:
    """Return zones whose polygon contains this address point, with their offerings."""
    addr = await db.execute(
        select(Address.rc_code).where(Address.rc_code == rc_code, Address.deleted_at.is_(None))
    )
    if addr.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Address not found")

    total = int(
        (
            await db.execute(
                text("""
                    SELECT COUNT(DISTINCT sz.id)
                    FROM addresses a
                    JOIN service_zones sz ON sz.polygon IS NOT NULL
                        AND ST_Contains(sz.polygon::geometry, a.point::geometry)
                    WHERE a.rc_code = :rc_code AND a.deleted_at IS NULL
                """),
                {"rc_code": rc_code},
            )
        ).scalar()
        or 0
    )

    rows = (await db.execute(text("""
        SELECT
            sz.id AS zone_id,
            sz.name AS zone_name,
            sz.priority AS zone_priority,
            zo.id AS offering_id,
            zo.zone_id AS offering_zone_id,
            zo.technology_id,
            zo.status,
            zo.max_download_mbps,
            zo.max_upload_mbps,
            zo.status_since,
            zo.planned_until,
            zo.notes,
            zo.created_at,
            zo.updated_at
        FROM addresses a
        JOIN (
            SELECT sz2.id, sz2.name, sz2.priority
            FROM service_zones sz2
            JOIN addresses a2 ON sz2.polygon IS NOT NULL
                AND ST_Contains(sz2.polygon::geometry, a2.point::geometry)
            WHERE a2.rc_code = :rc_code AND a2.deleted_at IS NULL
            ORDER BY sz2.priority DESC, sz2.name
            LIMIT :limit OFFSET :offset
        ) sz ON TRUE
        LEFT JOIN zone_offerings zo ON zo.zone_id = sz.id
        WHERE a.rc_code = :rc_code AND a.deleted_at IS NULL
        ORDER BY sz.priority DESC, sz.name
    """), {"rc_code": rc_code, "limit": page.limit, "offset": page.offset})).mappings().all()

    by_zone: dict[uuid.UUID, ZoneCoverageItem] = {}
    for row in rows:
        zid = row["zone_id"]
        if zid not in by_zone:
            by_zone[zid] = ZoneCoverageItem(
                zone_id=zid,
                zone_name=row["zone_name"],
                zone_priority=row["zone_priority"],
                offerings=[],
            )
        if row["offering_id"] is not None:
            by_zone[zid].offerings.append(
                ZoneOfferingOut(
                    id=row["offering_id"],
                    zone_id=row["offering_zone_id"],
                    technology_id=row["technology_id"],
                    status=row["status"],
                    max_download_mbps=row["max_download_mbps"],
                    max_upload_mbps=row["max_upload_mbps"],
                    status_since=row["status_since"],
                    planned_until=row["planned_until"],
                    notes=row["notes"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            )
    return Page[ZoneCoverageItem](total=total, items=list(by_zone.values()))


@router.get("/{rc_code}/offerings", response_model=Page[AddressOfferingOut], summary="List address offerings", operation_id="admin.addresses.offerings.list")
async def list_address_offerings(
    rc_code: int,
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[PaginationParams, Depends(pagination_params)],
) -> Page[AddressOfferingOut]:
    addr = await db.execute(
        select(Address.rc_code).where(Address.rc_code == rc_code, Address.deleted_at.is_(None))
    )
    if addr.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Address not found")
    total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(AddressOffering)
                .where(AddressOffering.address_code == rc_code)
            )
        ).scalar()
        or 0
    )
    result = await db.execute(
        select(AddressOffering)
        .where(AddressOffering.address_code == rc_code)
        .order_by(AddressOffering.created_at)
        .limit(page.limit)
        .offset(page.offset)
    )
    items = [AddressOfferingOut.model_validate(o) for o in result.scalars().all()]
    return Page[AddressOfferingOut](total=total, items=items)


@router.post("/{rc_code}/offerings", response_model=AddressOfferingOut, status_code=201, summary="Create address offering", operation_id="admin.addresses.offerings.create")
async def create_address_offering(
    rc_code: int,
    body: AddressOfferingCreate,
    current_user: Annotated[User, Depends(require_role("editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
) -> AddressOfferingOut:
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
        address_code=rc_code,
    )
    await db.commit()
    await db.refresh(offering)
    return created(
        AddressOfferingOut.model_validate(offering),
        location=f"/api/v1/admin/addresses/offerings/{offering.id}",
        response=response,
    )


@router.patch("/offerings/{offering_id}", response_model=AddressOfferingOut, summary="Update address offering", operation_id="admin.addresses.offerings.update")
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
    offering.updated_at = now()

    await log_action(
        db,
        current_user.id,
        "address_offering",
        str(offering_id),
        "update",
        {"address_code": offering.address_code, **changes},
        address_code=offering.address_code,
    )
    await db.commit()
    await db.refresh(offering)
    return offering


@router.delete(
    "/offerings/{offering_id}",
    status_code=204,
    summary="Delete an address-level offering. Editor+ can use this for quick correction.",
    operation_id="admin.addresses.offerings.delete",
)
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
        address_code=address_code,
    )
    await db.commit()


async def _require_offering(db: AsyncSession, offering_id: uuid.UUID) -> AddressOffering:
    result = await db.execute(select(AddressOffering).where(AddressOffering.id == offering_id))
    offering = result.scalar_one_or_none()
    if offering is None:
        raise HTTPException(status_code=404, detail="Offering not found")
    return offering
