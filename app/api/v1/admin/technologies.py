import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import Page, PaginationParams, pagination_params
from app.api.responses import created
from app.audit import log_action
from app.auth import require_role
from app.dependencies import get_db
from app.models.admin import User
from app.models.technology import Technology, TechnologyType
from app.schemas.admin import (
    TechnologyCreate,
    TechnologyOut,
    TechnologyTypeOut,
    TechnologyTypeUpdate,
    TechnologyUpdate,
)
from app.time import now

router = APIRouter(prefix="/api/v1/admin", tags=["admin-technologies"])


@router.get("/technology-types", response_model=Page[TechnologyTypeOut], summary="List technology types", operation_id="admin.technology-types.list")
async def list_technology_types(
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[PaginationParams, Depends(pagination_params)],
    q: Annotated[str | None, Query(description="substring on name")] = None,
) -> Page[TechnologyTypeOut]:
    stmt = select(TechnologyType).where(TechnologyType.deleted_at.is_(None))
    count_stmt = select(func.count()).select_from(TechnologyType).where(TechnologyType.deleted_at.is_(None))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(TechnologyType.display_name.ilike(like))
        count_stmt = count_stmt.where(TechnologyType.display_name.ilike(like))
    total = int((await db.execute(count_stmt)).scalar() or 0)
    result = await db.execute(
        stmt.order_by(TechnologyType.sort_order).limit(page.limit).offset(page.offset)
    )
    items = [TechnologyTypeOut.model_validate(t) for t in result.scalars().all()]
    return Page[TechnologyTypeOut](total=total, items=items)


@router.patch("/technology-types/{type_id}", response_model=TechnologyTypeOut, summary="Update technology type", operation_id="admin.technology-types.update")
async def update_technology_type(
    type_id: uuid.UUID,
    body: TechnologyTypeUpdate,
    current_user: Annotated[User, Depends(require_role("admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TechnologyType:
    tt = await _require_type(db, type_id)

    changes = body.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(tt, field, value)

    await log_action(db, current_user.id, "technology_type", str(type_id), "update", changes)
    await db.commit()
    await db.refresh(tt)
    return tt


@router.get("/technologies", response_model=Page[TechnologyOut], summary="List technologies", operation_id="admin.technologies.list")
async def list_technologies(
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[PaginationParams, Depends(pagination_params)],
    q: Annotated[str | None, Query(description="substring on name or variant_code")] = None,
    type_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[TechnologyOut]:
    stmt = select(Technology).where(Technology.deleted_at.is_(None))
    count_stmt = select(func.count()).select_from(Technology).where(Technology.deleted_at.is_(None))
    if q:
        like = f"%{q}%"
        cond = or_(Technology.display_name.ilike(like), Technology.variant_code.ilike(like))
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if type_id:
        stmt = stmt.where(Technology.type_id == type_id)
        count_stmt = count_stmt.where(Technology.type_id == type_id)
    total = int((await db.execute(count_stmt)).scalar() or 0)
    result = await db.execute(
        stmt.order_by(Technology.sort_order).limit(page.limit).offset(page.offset)
    )
    items = [TechnologyOut.model_validate(t) for t in result.scalars().all()]
    return Page[TechnologyOut](total=total, items=items)


@router.post("/technologies", response_model=TechnologyOut, status_code=201, summary="Create technology", operation_id="admin.technologies.create")
async def create_technology(
    body: TechnologyCreate,
    current_user: Annotated[User, Depends(require_role("admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
) -> TechnologyOut:
    existing = await db.execute(
        select(Technology).where(Technology.variant_code == body.variant_code)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="variant_code already exists")

    tech = Technology(**body.model_dump())
    db.add(tech)
    await db.flush()
    await log_action(db, current_user.id, "technology", str(tech.id), "create", body.model_dump())
    await db.commit()
    await db.refresh(tech)
    return created(
        TechnologyOut.model_validate(tech),
        location=f"/api/v1/admin/technologies/{tech.id}",
        response=response,
    )


@router.patch("/technologies/{tech_id}", response_model=TechnologyOut, summary="Update technology", operation_id="admin.technologies.update")
async def update_technology(
    tech_id: uuid.UUID,
    body: TechnologyUpdate,
    current_user: Annotated[User, Depends(require_role("admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Technology:
    tech = await _require_tech(db, tech_id)

    changes = body.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(tech, field, value)

    await log_action(db, current_user.id, "technology", str(tech_id), "update", changes)
    await db.commit()
    await db.refresh(tech)
    return tech


@router.delete("/technologies/{tech_id}", status_code=204, summary="Delete technology", operation_id="admin.technologies.delete")
async def delete_technology(
    tech_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role("admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    tech = await _require_tech(db, tech_id)
    tech.deleted_at = now()
    await log_action(db, current_user.id, "technology", str(tech_id), "delete")
    await db.commit()


async def _require_type(db: AsyncSession, type_id: uuid.UUID) -> TechnologyType:
    result = await db.execute(
        select(TechnologyType).where(TechnologyType.id == type_id, TechnologyType.deleted_at.is_(None))
    )
    tt = result.scalar_one_or_none()
    if tt is None:
        raise HTTPException(status_code=404, detail="Technology type not found")
    return tt


async def _require_tech(db: AsyncSession, tech_id: uuid.UUID) -> Technology:
    result = await db.execute(
        select(Technology).where(Technology.id == tech_id, Technology.deleted_at.is_(None))
    )
    tech = result.scalar_one_or_none()
    if tech is None:
        raise HTTPException(status_code=404, detail="Technology not found")
    return tech
