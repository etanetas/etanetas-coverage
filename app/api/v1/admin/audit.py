import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_role
from app.dependencies import get_db
from app.models.admin import AuditLog, User
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


@router.get("/audit-log", response_model=list[AuditLogOut])
async def get_audit_log(
    current_user: Annotated[User, Depends(require_role("admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    entity_type: str | None = Query(None),
    entity_id: str | None = Query(None),
    user_id: uuid.UUID | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditLogOut]:
    filters = []
    params: dict = {"limit": limit, "offset": offset}

    if entity_type:
        filters.append("al.entity_type = :entity_type")
        params["entity_type"] = entity_type
    if entity_id:
        filters.append("al.entity_id = :entity_id")
        params["entity_id"] = entity_id
    if user_id:
        filters.append("al.user_id = :user_id")
        params["user_id"] = str(user_id)
    if since:
        filters.append("al.at >= :since")
        params["since"] = since
    if until:
        filters.append("al.at <= :until")
        params["until"] = until

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    sql = text(f"{_AUDIT_SELECT} {where} ORDER BY al.at DESC LIMIT :limit OFFSET :offset")
    rows = (await db.execute(sql, params)).mappings().all()
    return [AuditLogOut(**r) for r in rows]


@router.get("/addresses/{rc_code}/history", response_model=list[AuditLogOut])
async def get_address_history(
    rc_code: int,
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditLogOut]:
    sql = text(f"""
        {_AUDIT_SELECT}
        WHERE al.entity_type = 'address_offering'
          AND (al.diff->>'address_code')::bigint = :rc_code
        ORDER BY al.at DESC
        LIMIT :limit OFFSET :offset
    """)
    rows = (await db.execute(sql, {"rc_code": rc_code, "limit": limit, "offset": offset})).mappings().all()
    return [AuditLogOut(**r) for r in rows]
