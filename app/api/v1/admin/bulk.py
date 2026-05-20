import json
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.auth import require_role
from app.dependencies import get_db
from app.models.admin import BulkOperations, User
from app.models.service import AddressOffering
from app.schemas.admin import (
    AddOfferingOperation,
    BulkExecuteRequest,
    BulkExecuteResponse,
    BulkFilter,
    BulkOperationOut,
    BulkPreviewRequest,
    BulkPreviewResponse,
    BulkSampleItem,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin-bulk"])

# In-memory preview token store.  Acceptable for single-process; the 5-min
# window is short enough that a restart simply invalidates open previews.
_preview_store: dict[str, dict] = {}

_EDITOR_RATE_LIMIT = 5000  # addresses per minute per editor

_MUNI_SHORT = "replace(replace(m.name, ' rajono', ' raj.'), ' miesto', ' m.')"
_LOCALITY_LABEL = f"""
    CASE l.type WHEN 'miestas' THEN l.name
    ELSE l.name || COALESCE(' ' || l.type_abbr, '') || ', ' || ({_MUNI_SHORT}) END
"""
_STREET_WITH_TYPE = "s.name || COALESCE(' ' || s.type_abbr, '')"
_HOUSE = "a.house_no || COALESCE(' k.' || a.corpus_no, '')"
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


@router.post("/bulk/preview", response_model=BulkPreviewResponse)
async def bulk_preview(
    body: BulkPreviewRequest,
    current_user: Annotated[User, Depends(require_role("editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BulkPreviewResponse:
    if body.filter.is_empty():
        raise HTTPException(status_code=422, detail="At least one filter field is required")

    rc_codes = await _filter_addresses(db, body.filter)
    if not rc_codes:
        return BulkPreviewResponse(affected_count=0, sample=[], preview_token=None)

    sample = await _build_sample(db, rc_codes[:5], body.operation)

    token = "tmp_" + secrets.token_urlsafe(16)
    _preview_store[token] = {
        "user_id": str(current_user.id),
        "operation": body.operation.model_dump(),
        "rc_codes": rc_codes,
        "expires_at": datetime.now() + timedelta(minutes=5),
    }
    _evict_expired()

    return BulkPreviewResponse(affected_count=len(rc_codes), sample=sample, preview_token=token)


@router.post("/bulk/execute", response_model=BulkExecuteResponse, status_code=201)
async def bulk_execute(
    body: BulkExecuteRequest,
    current_user: Annotated[User, Depends(require_role("editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BulkExecuteResponse:
    preview = _consume_token(body.preview_token, current_user.id)

    rc_codes: list[int] = preview["rc_codes"]

    if current_user.role == "editor":
        recent = await _recent_modified_count(db, current_user.id)
        if recent + len(rc_codes) > _EDITOR_RATE_LIMIT:
            raise HTTPException(
                status_code=422,
                detail=f"Rate limit: editor cannot affect more than {_EDITOR_RATE_LIMIT} addresses per minute. Contact an admin.",
            )

    op_data: dict = preview["operation"]
    op = AddOfferingOperation(**op_data)

    bulk_op = BulkOperations(
        user_id=current_user.id,
        operation_type=op.type,
        filter_criteria={},
        affected_count=len(rc_codes),
        rollback_data=None,
    )
    db.add(bulk_op)
    await db.flush()

    created_codes = await _execute_add_offering(db, bulk_op.id, current_user.id, op, rc_codes)

    bulk_op.rollback_data = {
        "type": op.type,
        "technology_id": str(op.technology_id),
        "created_codes": created_codes,
    }
    bulk_op.affected_count = len(created_codes)

    await log_action(db, current_user.id, "bulk_operation", str(bulk_op.id), "execute",
                     {"type": op.type, "affected_count": len(created_codes)})
    await db.commit()

    return BulkExecuteResponse(bulk_operation_id=bulk_op.id, modified_count=len(created_codes))


@router.post("/bulk/{bulk_op_id}/rollback", status_code=204)
async def bulk_rollback(
    bulk_op_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role("editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    result = await db.execute(select(BulkOperations).where(BulkOperations.id == bulk_op_id))
    bulk_op = result.scalar_one_or_none()
    if bulk_op is None:
        raise HTTPException(status_code=404, detail="Bulk operation not found")
    if bulk_op.rolled_back_at is not None:
        raise HTTPException(status_code=409, detail="Already rolled back")

    if current_user.role == "editor":
        if bulk_op.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Can only rollback your own operations")
        if datetime.now() - bulk_op.created_at > timedelta(minutes=15):
            raise HTTPException(status_code=403, detail="Rollback window expired (15 min)")

    rd = bulk_op.rollback_data or {}
    created_codes: list[int] = rd.get("created_codes", [])
    tech_id: str | None = rd.get("technology_id")

    if created_codes and tech_id:
        await db.execute(
            text("""
                DELETE FROM address_offerings
                WHERE bulk_operation_id = CAST(:bulk_op_id AS uuid)
                  AND address_code = ANY(:codes)
                  AND technology_id = CAST(:tech_id AS uuid)
            """),
            {"bulk_op_id": str(bulk_op_id), "codes": created_codes, "tech_id": tech_id},
        )

    bulk_op.rolled_back_at = datetime.now()
    await log_action(db, current_user.id, "bulk_operation", str(bulk_op_id), "rollback",
                     {"rolled_back_count": len(created_codes)})
    await db.commit()


@router.get("/bulk-operations", response_model=list[BulkOperationOut])
async def list_bulk_operations(
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[BulkOperationOut]:
    rows = (await db.execute(text("""
        SELECT bo.id, bo.user_id, u.username, bo.operation_type,
               bo.affected_count, bo.created_at, bo.rolled_back_at
        FROM bulk_operations bo
        LEFT JOIN users u ON u.id = bo.user_id
        ORDER BY bo.created_at DESC
        LIMIT 200
    """))).mappings().all()
    return [BulkOperationOut(**r) for r in rows]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _filter_addresses(db: AsyncSession, f: BulkFilter) -> list[int]:
    filters = ["a.deleted_at IS NULL", "a.address_type = 'building'"]
    params: dict = {}

    if f.rc_codes:
        filters.append("a.rc_code = ANY(:rc_codes)")
        params["rc_codes"] = f.rc_codes
    if f.locality_code:
        filters.append("a.locality_code = :locality_code")
        params["locality_code"] = f.locality_code
    if f.street_codes:
        filters.append("a.street_code = ANY(:street_codes)")
        params["street_codes"] = f.street_codes
    if f.house_no_pattern:
        filters.append("a.house_no ILIKE :house_no_pattern")
        params["house_no_pattern"] = f.house_no_pattern

    sql = text(
        f"SELECT a.rc_code FROM addresses a WHERE {' AND '.join(filters)} ORDER BY a.rc_code LIMIT 10000"
    )
    result = await db.execute(sql, params)
    return [row[0] for row in result.fetchall()]


async def _build_sample(
    db: AsyncSession, rc_codes: list[int], op: AddOfferingOperation
) -> list[BulkSampleItem]:
    if not rc_codes:
        return []

    addr_sql = text(f"""
        SELECT a.rc_code, {_FULL_ADDRESS} AS full_address
        FROM addresses a {_ADDR_JOINS}
        WHERE a.rc_code = ANY(:codes)
    """)
    addr_rows = {r["rc_code"]: r["full_address"]
                 for r in (await db.execute(addr_sql, {"codes": rc_codes})).mappings().all()}

    existing_sql = text("""
        SELECT address_code, status, max_download_mbps, max_upload_mbps
        FROM address_offerings
        WHERE address_code = ANY(:codes) AND technology_id = CAST(:tech_id AS uuid)
    """)
    existing = {
        r["address_code"]: {"status": r["status"], "max_dl_mbps": r["max_download_mbps"], "max_ul_mbps": r["max_upload_mbps"]}
        for r in (await db.execute(existing_sql, {"codes": rc_codes, "tech_id": str(op.technology_id)})).mappings().all()
    }

    new_state = {
        "status": op.status,
        "max_dl_mbps": op.max_dl_mbps,
        "max_ul_mbps": op.max_ul_mbps,
        "status_since": str(op.status_since),
    }
    return [
        BulkSampleItem(
            address=addr_rows.get(rc, str(rc)),
            current=existing.get(rc),
            new=new_state,
        )
        for rc in rc_codes
    ]


async def _execute_add_offering(
    db: AsyncSession,
    bulk_op_id: uuid.UUID,
    user_id: uuid.UUID,
    op: AddOfferingOperation,
    rc_codes: list[int],
) -> list[int]:
    now = datetime.now()
    rows = [
        {
            "address_code": rc,
            "technology_id": op.technology_id,
            "status": op.status,
            "max_download_mbps": op.max_dl_mbps,
            "max_upload_mbps": op.max_ul_mbps,
            "status_since": op.status_since,
            "planned_until": op.planned_until,
            "notes": op.notes,
            "created_by": user_id,
            "bulk_operation_id": bulk_op_id,
            "created_at": now,
            "updated_at": now,
        }
        for rc in rc_codes
    ]

    stmt = (
        pg_insert(AddressOffering)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["address_code", "technology_id"])
        .returning(AddressOffering.address_code)
    )
    result = await db.execute(stmt)
    created = [row[0] for row in result.fetchall()]

    # Batch audit entries for created offerings
    if created:
        diff_json = json.dumps({"bulk_operation_id": str(bulk_op_id), "status": op.status})
        await db.execute(
            text("""
                INSERT INTO audit_log (user_id, entity_type, entity_id, action, diff, at)
                SELECT
                    CAST(:user_id AS uuid),
                    'address_offering',
                    CAST(ao.id AS text),
                    'create',
                    CAST(:diff AS jsonb),
                    NOW()
                FROM address_offerings ao
                WHERE ao.bulk_operation_id = CAST(:bulk_op_id AS uuid)
            """),
            {"user_id": str(user_id), "bulk_op_id": str(bulk_op_id), "diff": diff_json},
        )

    return created


async def _recent_modified_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(
        text("""
            SELECT COALESCE(SUM(affected_count), 0)
            FROM bulk_operations
            WHERE user_id = :user_id
              AND created_at > NOW() - INTERVAL '1 minute'
              AND rolled_back_at IS NULL
        """),
        {"user_id": str(user_id)},
    )
    return int(result.scalar() or 0)


def _consume_token(token: str, user_id: uuid.UUID) -> dict:
    data = _preview_store.pop(token, None)
    if data is None:
        raise HTTPException(status_code=422, detail="Invalid or expired preview token")
    if data["user_id"] != str(user_id):
        _preview_store[token] = data  # put it back
        raise HTTPException(status_code=403, detail="Preview token belongs to a different user")
    if datetime.now() > data["expires_at"]:
        raise HTTPException(status_code=422, detail="Preview token expired (5 min limit)")
    return data


def _evict_expired() -> None:
    now = datetime.now()
    expired = [k for k, v in _preview_store.items() if now > v["expires_at"]]
    for k in expired:
        del _preview_store[k]
