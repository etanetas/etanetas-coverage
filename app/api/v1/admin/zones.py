import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import Page, PaginationParams, pagination_params
from app.api.responses import created
from app.audit import log_action
from app.auth import require_role
from app.db.filter_builder import build_where
from app.dependencies import get_db
from app.models.admin import User
from app.models.service import ServiceZone, ZoneOffering
from app.schemas.admin import (
    ZoneCreate,
    ZoneDetail,
    ZoneOfferingCreate,
    ZoneOfferingOut,
    ZoneOfferingUpdate,
    ZoneOut,
    ZoneUpdate,
)
from app.time import now

router = APIRouter(prefix="/api/v1/admin/zones", tags=["admin-zones"])


@router.get("", response_model=Page[ZoneOut], summary="List zones", operation_id="admin.zones.list")
async def list_zones(
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[PaginationParams, Depends(pagination_params)],
    q: Annotated[str | None, Query(description="substring match on zone name")] = None,
    priority_min: Annotated[int | None, Query()] = None,
) -> Page[ZoneOut]:
    where, params = build_where([
        ("deleted_at IS NULL", {}),
        ("name ILIKE :q", {"q": f"%{q}%"}) if q else None,
        ("priority >= :priority_min", {"priority_min": priority_min}) if priority_min is not None else None,
    ])

    total = int(
        (await db.execute(text(f"SELECT COUNT(*) FROM service_zones {where}"), params)).scalar() or 0
    )

    params["limit"] = page.limit
    params["offset"] = page.offset
    rows = (await db.execute(text(f"""
        SELECT
            id, name, description, priority, created_at,
            polygon IS NOT NULL AS has_polygon,
            CASE WHEN polygon IS NOT NULL
                 THEN ST_AsGeoJSON(ST_SimplifyPreserveTopology(polygon::geometry, 0.001))::jsonb
                 ELSE NULL
            END AS polygon_geojson
        FROM service_zones
        {where}
        ORDER BY priority DESC, name
        LIMIT :limit OFFSET :offset
    """), params)).mappings().all()
    items = [ZoneOut(
        id=r["id"],
        name=r["name"],
        description=r["description"],
        priority=r["priority"],
        has_polygon=r["has_polygon"],
        polygon_geojson=r["polygon_geojson"],
        created_at=r["created_at"],
    ) for r in rows]
    return Page[ZoneOut](total=total, items=items)


@router.get("/{zone_id}/detail", response_model=ZoneDetail, summary="Get zone detail", operation_id="admin.zones.get-detail")
async def get_zone_detail(
    zone_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ZoneDetail:
    """Full zone detail with polygon GeoJSON, offerings, and address count."""
    zone = await _require_zone(db, zone_id)

    polygon_row = (await db.execute(text("""
        SELECT
            CASE WHEN polygon IS NOT NULL
                 THEN ST_AsGeoJSON(ST_SimplifyPreserveTopology(polygon::geometry, 0.0001))::jsonb
                 ELSE NULL
            END AS polygon_geojson
        FROM service_zones WHERE id = CAST(:id AS uuid)
    """), {"id": str(zone_id)})).mappings().first()

    count_row = (await db.execute(text("""
        SELECT COUNT(*) AS cnt
        FROM addresses a
        JOIN service_zones z ON ST_Contains(z.polygon::geometry, a.point::geometry)
        WHERE z.id = CAST(:id AS uuid) AND a.deleted_at IS NULL
    """), {"id": str(zone_id)})).first()

    offerings_result = await db.execute(
        select(ZoneOffering).where(ZoneOffering.zone_id == zone_id).order_by(ZoneOffering.created_at)
    )
    offerings = list(offerings_result.scalars().all())

    return ZoneDetail(
        id=zone.id,
        name=zone.name,
        description=zone.description,
        priority=zone.priority,
        has_polygon=zone.polygon is not None,
        polygon_geojson=polygon_row["polygon_geojson"] if polygon_row else None,
        created_at=zone.created_at,
        offerings=offerings,
        address_count=int(count_row[0]) if count_row and zone.polygon is not None else 0,
    )


@router.post("", response_model=ZoneOut, status_code=201, summary="Create zone", operation_id="admin.zones.create")
async def create_zone(
    body: ZoneCreate,
    current_user: Annotated[User, Depends(require_role("editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
) -> ZoneOut:
    zone = ServiceZone(
        name=body.name,
        description=body.description,
        priority=body.priority,
        created_by=current_user.id,
    )
    db.add(zone)
    await db.flush()

    if body.polygon_geojson is not None:
        await db.execute(
            text("UPDATE service_zones SET polygon = ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326) WHERE id = :id"),
            {"geojson": body.polygon_geojson.model_dump_json(), "id": str(zone.id)},
        )

    await log_action(db, current_user.id, "service_zone", str(zone.id), "create",
                     {"name": body.name, "priority": body.priority})
    await db.commit()
    await db.refresh(zone)
    return created(
        ZoneOut(
            id=zone.id,
            name=zone.name,
            description=zone.description,
            priority=zone.priority,
            has_polygon=zone.polygon is not None,
            polygon_geojson=body.polygon_geojson.model_dump() if body.polygon_geojson is not None else None,
            created_at=zone.created_at,
        ),
        location=f"/api/v1/admin/zones/{zone.id}",
        response=response,
    )


@router.patch("/{zone_id}", response_model=ZoneOut, summary="Update zone", operation_id="admin.zones.update")
async def update_zone(
    zone_id: uuid.UUID,
    body: ZoneUpdate,
    current_user: Annotated[User, Depends(require_role("editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ZoneOut:
    zone = await _require_zone(db, zone_id)

    fields = body.model_fields_set

    if "name" in fields and body.name is not None:
        zone.name = body.name
    if "description" in fields:
        zone.description = body.description
    if "priority" in fields and body.priority is not None:
        zone.priority = body.priority

    if "polygon_geojson" in fields:
        await db.flush()
        if body.polygon_geojson is None:
            await db.execute(
                text("UPDATE service_zones SET polygon = NULL WHERE id = :id"),
                {"id": str(zone_id)},
            )
        else:
            await db.execute(
                text("UPDATE service_zones SET polygon = ST_SetSRID(ST_GeomFromGeoJSON(:gj), 4326) WHERE id = :id"),
                {"gj": body.polygon_geojson.model_dump_json(), "id": str(zone_id)},
            )

    changes = body.model_dump(exclude_none=True, exclude={"polygon_geojson"})
    await log_action(db, current_user.id, "service_zone", str(zone_id), "update", changes or None)
    await db.commit()
    await db.refresh(zone)
    return ZoneOut(
        id=zone.id,
        name=zone.name,
        description=zone.description,
        priority=zone.priority,
        has_polygon=zone.polygon is not None,
        polygon_geojson=None,
        created_at=zone.created_at,
    )


@router.delete("/{zone_id}", status_code=204, summary="Delete zone", operation_id="admin.zones.delete")
async def delete_zone(
    zone_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role("admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    zone = await _require_zone(db, zone_id)
    zone.deleted_at = now()
    await log_action(db, current_user.id, "service_zone", str(zone_id), "delete", {"name": zone.name})
    await db.commit()


@router.get("/{zone_id}/offerings", response_model=Page[ZoneOfferingOut], summary="List zone offerings", operation_id="admin.zones.offerings.list")
async def list_zone_offerings(
    zone_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[PaginationParams, Depends(pagination_params)],
) -> Page[ZoneOfferingOut]:
    await _require_zone(db, zone_id)
    total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ZoneOffering)
                .where(ZoneOffering.zone_id == zone_id)
            )
        ).scalar()
        or 0
    )
    result = await db.execute(
        select(ZoneOffering)
        .where(ZoneOffering.zone_id == zone_id)
        .order_by(ZoneOffering.created_at)
        .limit(page.limit)
        .offset(page.offset)
    )
    items = [ZoneOfferingOut.model_validate(o) for o in result.scalars().all()]
    return Page[ZoneOfferingOut](total=total, items=items)


@router.post("/{zone_id}/offerings", response_model=ZoneOfferingOut, status_code=201, summary="Create zone offering", operation_id="admin.zones.offerings.create")
async def create_zone_offering(
    zone_id: uuid.UUID,
    body: ZoneOfferingCreate,
    current_user: Annotated[User, Depends(require_role("editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
) -> ZoneOfferingOut:
    await _require_zone(db, zone_id)

    existing = await db.execute(
        select(ZoneOffering).where(
            ZoneOffering.zone_id == zone_id,
            ZoneOffering.technology_id == body.technology_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Offering for this technology already exists in zone")

    offering = ZoneOffering(zone_id=zone_id, **body.model_dump())
    db.add(offering)
    await db.flush()
    await log_action(db, current_user.id, "zone_offering", str(offering.id), "create",
                     {"zone_id": str(zone_id), **body.model_dump()})
    await db.commit()
    await db.refresh(offering)
    return created(
        ZoneOfferingOut.model_validate(offering),
        location=f"/api/v1/admin/zones/offerings/{offering.id}",
        response=response,
    )


@router.patch("/offerings/{offering_id}", response_model=ZoneOfferingOut, summary="Update zone offering", operation_id="admin.zones.offerings.update")
async def update_zone_offering(
    offering_id: uuid.UUID,
    body: ZoneOfferingUpdate,
    current_user: Annotated[User, Depends(require_role("editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ZoneOffering:
    offering = await _require_offering(db, offering_id)

    changes = body.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(offering, field, value)
    offering.updated_at = now()

    await log_action(db, current_user.id, "zone_offering", str(offering_id), "update", changes)
    await db.commit()
    await db.refresh(offering)
    return offering


@router.delete("/offerings/{offering_id}", status_code=204, summary="Delete zone offering", operation_id="admin.zones.offerings.delete")
async def delete_zone_offering(
    offering_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role("editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    offering = await _require_offering(db, offering_id)
    zone_id = offering.zone_id
    await db.delete(offering)
    await log_action(db, current_user.id, "zone_offering", str(offering_id), "delete",
                     {"zone_id": str(zone_id)})
    await db.commit()


class ZoneAddressItem(BaseModel):
    rc_code: int
    full_address: str
    postal_code: str | None
    has_override: bool  # True if this address has its own address_offering


@router.get("/{zone_id}/addresses", response_model=Page[ZoneAddressItem], summary="List addresses in zone", operation_id="admin.zones.addresses.list")
async def list_zone_addresses(
    zone_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[PaginationParams, Depends(pagination_params)],
) -> Page[ZoneAddressItem]:
    """List addresses (buildings) inside a zone's polygon. Paginated."""
    await _require_zone(db, zone_id)

    total_row = await db.execute(text("""
        SELECT COUNT(*) FROM addresses a
        JOIN service_zones z ON ST_Contains(z.polygon::geometry, a.point::geometry)
        WHERE z.id = CAST(:zid AS uuid)
          AND z.deleted_at IS NULL
          AND a.deleted_at IS NULL
          AND a.address_type = 'building'
    """), {"zid": str(zone_id)})
    total = int(total_row.scalar() or 0)

    rows = (await db.execute(text("""
        SELECT
            a.rc_code,
            (COALESCE(s.name || ' ', '') || a.house_no || ', ' || l.name) AS full_address,
            a.postal_code,
            EXISTS(SELECT 1 FROM address_offerings ao WHERE ao.address_code = a.rc_code) AS has_override
        FROM addresses a
        JOIN service_zones z ON ST_Contains(z.polygon::geometry, a.point::geometry)
        JOIN localities l ON l.rc_code = a.locality_code
        LEFT JOIN streets s ON s.rc_code = a.street_code
        WHERE z.id = CAST(:zid AS uuid)
          AND z.deleted_at IS NULL
          AND a.deleted_at IS NULL
          AND a.address_type = 'building'
        ORDER BY a.rc_code
        LIMIT :limit OFFSET :offset
    """), {"zid": str(zone_id), "limit": page.limit, "offset": page.offset})).mappings().all()

    return Page[ZoneAddressItem](
        total=total,
        items=[ZoneAddressItem(**r) for r in rows],
    )


async def _require_zone(db: AsyncSession, zone_id: uuid.UUID) -> ServiceZone:
    result = await db.execute(
        select(ServiceZone).where(ServiceZone.id == zone_id, ServiceZone.deleted_at.is_(None))
    )
    zone = result.scalar_one_or_none()
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    return zone


async def _require_offering(db: AsyncSession, offering_id: uuid.UUID) -> ZoneOffering:
    result = await db.execute(select(ZoneOffering).where(ZoneOffering.id == offering_id))
    offering = result.scalar_one_or_none()
    if offering is None:
        raise HTTPException(status_code=404, detail="Zone offering not found")
    return offering
