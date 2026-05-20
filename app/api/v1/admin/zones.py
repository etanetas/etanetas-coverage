import json
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
from app.models.service import ServiceZone, ZoneOffering
from app.schemas.admin import ZoneCreate, ZoneOfferingCreate, ZoneOfferingOut, ZoneOut, ZoneUpdate

router = APIRouter(prefix="/api/v1/admin/zones", tags=["admin-zones"])


@router.get("", response_model=list[ZoneOut])
async def list_zones(
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ZoneOut]:
    result = await db.execute(select(ServiceZone).order_by(ServiceZone.priority.desc(), ServiceZone.name))
    zones = result.scalars().all()
    return [ZoneOut(
        id=z.id,
        name=z.name,
        description=z.description,
        priority=z.priority,
        has_polygon=z.polygon is not None,
        created_at=z.created_at,
    ) for z in zones]


@router.post("", response_model=ZoneOut, status_code=201)
async def create_zone(
    body: ZoneCreate,
    current_user: Annotated[User, Depends(require_role("editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
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
            {"geojson": json.dumps(body.polygon_geojson), "id": str(zone.id)},
        )

    await log_action(db, current_user.id, "service_zone", str(zone.id), "create",
                     {"name": body.name, "priority": body.priority})
    await db.commit()
    await db.refresh(zone)
    return ZoneOut(
        id=zone.id,
        name=zone.name,
        description=zone.description,
        priority=zone.priority,
        has_polygon=zone.polygon is not None,
        created_at=zone.created_at,
    )


@router.put("/{zone_id}", response_model=ZoneOut)
async def update_zone(
    zone_id: uuid.UUID,
    body: ZoneUpdate,
    current_user: Annotated[User, Depends(require_role("editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ZoneOut:
    zone = await _require_zone(db, zone_id)

    if body.name is not None:
        zone.name = body.name
    if body.description is not None:
        zone.description = body.description
    if body.priority is not None:
        zone.priority = body.priority

    if body.polygon_geojson is not None:
        await db.flush()
        await db.execute(
            text("UPDATE service_zones SET polygon = ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326) WHERE id = :id"),
            {"geojson": json.dumps(body.polygon_geojson), "id": str(zone_id)},
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
        created_at=zone.created_at,
    )


@router.delete("/{zone_id}", status_code=204)
async def delete_zone(
    zone_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role("admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    zone = await _require_zone(db, zone_id)
    await log_action(db, current_user.id, "service_zone", str(zone_id), "delete", {"name": zone.name})
    await db.delete(zone)
    await db.commit()


@router.get("/{zone_id}/offerings", response_model=list[ZoneOfferingOut])
async def list_zone_offerings(
    zone_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ZoneOffering]:
    await _require_zone(db, zone_id)
    result = await db.execute(
        select(ZoneOffering)
        .where(ZoneOffering.zone_id == zone_id)
        .order_by(ZoneOffering.created_at)
    )
    return list(result.scalars().all())


@router.post("/{zone_id}/offerings", response_model=ZoneOfferingOut, status_code=201)
async def create_zone_offering(
    zone_id: uuid.UUID,
    body: ZoneOfferingCreate,
    current_user: Annotated[User, Depends(require_role("editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ZoneOffering:
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
    return offering


async def _require_zone(db: AsyncSession, zone_id: uuid.UUID) -> ServiceZone:
    result = await db.execute(select(ServiceZone).where(ServiceZone.id == zone_id))
    zone = result.scalar_one_or_none()
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    return zone
