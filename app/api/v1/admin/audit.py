import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import Page, PaginationParams, pagination_params
from app.auth import require_role
from app.db.filter_builder import build_where
from app.dependencies import get_db
from app.models.admin import User
from app.schemas.admin import AuditLogOut

router = APIRouter(prefix="/api/v1/admin", tags=["admin-audit"])

_AUDIT_SELECT = """
    SELECT
        al.id,
        al.user_id,
        u.username,
        al.entity_type,
        al.entity_id,
        al.action,
        al.diff,
        al.at
    FROM audit_log al
    LEFT JOIN users u ON u.id = al.user_id
"""


@router.get("/audit-log", response_model=Page[AuditLogOut], summary="Query audit log", operation_id="admin.audit-log.list")
async def get_audit_log(
    current_user: Annotated[User, Depends(require_role("admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[PaginationParams, Depends(pagination_params)],
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    entity_id: Annotated[str | None, Query(max_length=128)] = None,
    user_id: uuid.UUID | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
) -> Page[AuditLogOut]:
    if since and until and since >= until:
        from app.errors import raise_error
        raise_error(422, "VALIDATION_ERROR", "`since` must be before `until`")

    where, params = build_where([
        ("al.entity_type = :entity_type", {"entity_type": entity_type}) if entity_type else None,
        ("al.entity_id = :entity_id", {"entity_id": entity_id}) if entity_id else None,
        ("al.user_id = :user_id", {"user_id": str(user_id)}) if user_id else None,
        ("al.at >= :since", {"since": since}) if since else None,
        ("al.at <= :until", {"until": until}) if until else None,
    ])
    total = int(
        (await db.execute(text(f"SELECT COUNT(*) FROM audit_log al {where}"), params)).scalar() or 0
    )

    params["limit"] = page.limit
    params["offset"] = page.offset
    sql = text(f"{_AUDIT_SELECT} {where} ORDER BY al.at DESC LIMIT :limit OFFSET :offset")
    rows = (await db.execute(sql, params)).mappings().all()
    return Page[AuditLogOut](total=total, items=[AuditLogOut(**r) for r in rows])


@router.get("/addresses/{rc_code}/history", response_model=Page[AuditLogOut], summary="Address change history", operation_id="admin.addresses.history.list")
async def get_address_history(
    rc_code: int,
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[PaginationParams, Depends(pagination_params)],
) -> Page[AuditLogOut]:
    where = (
        "WHERE al.address_code = :rc_code"
    )
    total = int(
        (
            await db.execute(
                text(f"SELECT COUNT(*) FROM audit_log al {where}"),
                {"rc_code": rc_code},
            )
        ).scalar()
        or 0
    )
    sql = text(f"""
        {_AUDIT_SELECT}
        {where}
        ORDER BY al.at DESC
        LIMIT :limit OFFSET :offset
    """)
    rows = (await db.execute(
        sql, {"rc_code": rc_code, "limit": page.limit, "offset": page.offset}
    )).mappings().all()
    return Page[AuditLogOut](total=total, items=[AuditLogOut(**r) for r in rows])
