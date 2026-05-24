import json
import logging
import secrets
import uuid
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import Page, PaginationParams, pagination_params
from app.api.responses import created
from app.audit import log_action
from app.auth import require_role
from app.dependencies import get_db
from app.errors import raise_error
from app.limiter import limiter
from app.models.address import Address
from app.models.admin import BulkOperations, BulkPreviewToken, User
from app.models.service import AddressOffering
from app.time import now

from app.db.address_labels import _ADDR_JOINS, _FULL_ADDRESS, _HOUSE, _LOCALITY_LABEL, _MUNI_SHORT, _STREET_WITH_TYPE  # noqa: F401

log = logging.getLogger(__name__)
from app.schemas.admin import (
    AddOfferingOperation,
    BulkExecuteRequest,
    BulkExecuteResponse,
    BulkFilter,
    BulkOperationDetailOut,
    BulkOperationOut,
    BulkPreviewRequest,
    BulkPreviewResponse,
    BulkRollbackResponse,
    BulkSampleItem,
    ChangeOfferingOperation,
    RemoveOfferingOperation,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin-bulk"])

_EDITOR_RATE_LIMIT = 5000  # addresses per minute per editor
_MAX_BULK_AFFECTED = 10_000


@router.post("/bulk/preview", response_model=BulkPreviewResponse)
@limiter.limit("30/minute")
async def bulk_preview(
    request: Request,
    body: BulkPreviewRequest,
    response: Response,
    current_user: Annotated[User, Depends(require_role("editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BulkPreviewResponse:
    if body.filter.is_empty():
        raise HTTPException(status_code=422, detail="At least one filter field is required")

    response.headers["Cache-Control"] = "no-store"

    rc_codes = await _filter_addresses(db, body.filter)
    if not rc_codes:
        return BulkPreviewResponse(affected_count=0, sample=[], preview_token=None)

    sample = await _build_sample(db, rc_codes[:5], body.operation)

    token = "tmp_" + secrets.token_urlsafe(16)
    expires_at = now() + timedelta(minutes=5)
    token_row = BulkPreviewToken(
        token=token,
        user_id=current_user.id,
        payload={
            "user_id": str(current_user.id),
            "operation": body.operation.model_dump(mode="json"),
            "filter": body.filter.model_dump(mode="json"),
            "rc_codes": rc_codes,
        },
        expires_at=expires_at,
    )
    db.add(token_row)
    await db.execute(
        delete(BulkPreviewToken).where(BulkPreviewToken.expires_at < now())
    )
    await db.commit()

    return BulkPreviewResponse(
        affected_count=len(rc_codes),
        sample=sample,
        preview_token=token,
        expires_at=expires_at,
    )


@router.post("/bulk/execute", response_model=BulkExecuteResponse, status_code=201)
@limiter.limit("10/minute")
async def bulk_execute(
    request: Request,
    body: BulkExecuteRequest,
    response: Response,
    current_user: Annotated[User, Depends(require_role("editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BulkExecuteResponse:
    preview = await _consume_token(body.preview_token, current_user.id, db)

    rc_codes: list[int] = preview["rc_codes"]

    if current_user.role == "editor":
        recent = await _recent_modified_count(db, current_user.id)
        if recent + len(rc_codes) > _EDITOR_RATE_LIMIT:
            raise HTTPException(
                status_code=422,
                detail=f"Rate limit: editor cannot affect more than {_EDITOR_RATE_LIMIT} addresses per minute. Contact an admin.",
            )

    op_data: dict = preview["operation"]
    op_type = op_data.get("type")

    bulk_op = BulkOperations(
        user_id=current_user.id,
        operation_type=op_type,
        filter_criteria=preview.get("filter", {}),
        affected_count=len(rc_codes),
        rollback_data=None,
    )
    db.add(bulk_op)
    await db.flush()

    # Dispatch based on operation type
    if op_type == "add_offering":
        op = AddOfferingOperation(**op_data)
        modified = await _execute_add_offering(db, bulk_op.id, current_user.id, op, rc_codes)
        bulk_op.rollback_data = {
            "type": "add_offering",
            "technology_id": str(op.technology_id),
            "created_codes": modified,
        }
    elif op_type == "change_offering":
        op = ChangeOfferingOperation(**op_data)
        modified, old_values = await _execute_change_offering(db, bulk_op.id, current_user.id, op, rc_codes)
        bulk_op.rollback_data = {
            "type": "change_offering",
            "technology_id": str(op.technology_id),
            "old_values": old_values,  # [{address_code, status, max_dl, max_ul, status_since, planned_until, notes}]
        }
    elif op_type == "remove_offering":
        op = RemoveOfferingOperation(**op_data)
        modified, deleted_data = await _execute_remove_offering(db, bulk_op.id, current_user.id, op, rc_codes)
        bulk_op.rollback_data = {
            "type": "remove_offering",
            "technology_id": str(op.technology_id),
            "deleted_offerings": deleted_data,  # full data of deleted rows
        }
    else:
        raise HTTPException(status_code=422, detail=f"Unknown operation type: {op_type}")

    bulk_op.affected_count = len(modified)

    await log_action(
        db,
        current_user.id,
        "bulk_operation",
        str(bulk_op.id),
        "execute",
        {"type": op_type, "affected_count": len(modified)},
    )
    await db.commit()

    return created(
        BulkExecuteResponse(bulk_operation_id=bulk_op.id, modified_count=len(modified)),
        location=f"/api/v1/admin/bulk-operations/{bulk_op.id}",
        response=response,
    )


@router.post("/bulk/{bulk_op_id}/rollback", response_model=BulkRollbackResponse)
async def bulk_rollback(
    bulk_op_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role("editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BulkRollbackResponse:
    result = await db.execute(select(BulkOperations).where(BulkOperations.id == bulk_op_id))
    bulk_op = result.scalar_one_or_none()
    if bulk_op is None:
        raise HTTPException(status_code=404, detail="Bulk operation not found")
    if bulk_op.rolled_back_at is not None:
        raise HTTPException(status_code=409, detail="Already rolled back")

    if current_user.role == "editor":
        if bulk_op.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Can only rollback your own operations")
        if now() - bulk_op.created_at > timedelta(minutes=15):
            raise HTTPException(status_code=403, detail="Rollback window expired (15 min)")

    rd = bulk_op.rollback_data or {}
    rd_type = rd.get("type")
    tech_id = rd.get("technology_id")
    affected = 0

    if rd_type == "add_offering":
        created_codes: list[int] = rd.get("created_codes", [])
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
            affected = len(created_codes)

    elif rd_type == "change_offering":
        # Restore old values via ORM (avoids asyncpg None CAST issues)
        old_values: list[dict] = rd.get("old_values", [])
        tech_uuid = uuid.UUID(tech_id) if tech_id else None
        for old in old_values:
            result = await db.execute(
                select(AddressOffering).where(
                    AddressOffering.address_code == old["address_code"],
                    AddressOffering.technology_id == tech_uuid,
                )
            )
            ao = result.scalar_one_or_none()
            if ao is None:
                continue
            ao.status = old["status"]
            ao.max_download_mbps = old["max_download_mbps"]
            ao.max_upload_mbps = old["max_upload_mbps"]
            ao.status_since = date.fromisoformat(old["status_since"]) if old.get("status_since") else None
            ao.planned_until = date.fromisoformat(old["planned_until"]) if old.get("planned_until") else None
            ao.notes = old.get("notes")
            ao.updated_at = now()
        affected = len(old_values)

    elif rd_type == "remove_offering":
        # Recreate deleted offerings via ORM
        deleted: list[dict] = rd.get("deleted_offerings", [])
        tech_uuid = uuid.UUID(tech_id) if tech_id else None
        for d in deleted:
            ao = AddressOffering(
                address_code=d["address_code"],
                technology_id=tech_uuid,
                status=d["status"],
                max_download_mbps=d["max_download_mbps"],
                max_upload_mbps=d["max_upload_mbps"],
                status_since=date.fromisoformat(d["status_since"]) if d.get("status_since") else None,
                planned_until=date.fromisoformat(d["planned_until"]) if d.get("planned_until") else None,
                notes=d.get("notes"),
                created_by=uuid.UUID(d["created_by"]),
            )
            db.add(ao)
        affected = len(deleted)

    bulk_op.rolled_back_at = now()
    await log_action(
        db,
        current_user.id,
        "bulk_operation",
        str(bulk_op_id),
        "rollback",
        {"rolled_back_count": affected, "type": rd_type},
    )
    await db.commit()
    return BulkRollbackResponse(rolled_back_count=affected)


@router.get("/bulk-operations", response_model=Page[BulkOperationOut])
async def list_bulk_operations(
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[PaginationParams, Depends(pagination_params)],
) -> Page[BulkOperationOut]:
    total = int(
        (await db.execute(text("SELECT COUNT(*) FROM bulk_operations"))).scalar() or 0
    )
    rows = (
        await db.execute(
            text("""
                SELECT bo.id, bo.user_id, u.username, bo.operation_type,
                       bo.affected_count, bo.created_at, bo.rolled_back_at
                FROM bulk_operations bo
                LEFT JOIN users u ON u.id = bo.user_id
                ORDER BY bo.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"limit": page.limit, "offset": page.offset},
        )
    ).mappings().all()
    return Page[BulkOperationOut](
        total=total, items=[BulkOperationOut(**r) for r in rows]
    )


@router.get(
    "/bulk-operations/{op_id}",
    response_model=BulkOperationDetailOut,
    summary="Get a single bulk operation",
)
async def get_bulk_operation(
    op_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BulkOperationDetailOut:
    row = (
        await db.execute(
            text("""
                SELECT bo.id, bo.user_id, u.username, bo.operation_type,
                       bo.affected_count, bo.created_at, bo.rolled_back_at,
                       bo.filter_criteria
                FROM bulk_operations bo
                LEFT JOIN users u ON u.id = bo.user_id
                WHERE bo.id = :id
            """),
            {"id": str(op_id)},
        )
    ).mappings().first()
    if row is None:
        raise_error(404, "NOT_FOUND", "Bulk operation not found")
    return BulkOperationDetailOut(**row)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_filter_where(f: BulkFilter) -> tuple[str, dict]:
    """Return (where_clause_string, params_dict) for a BulkFilter."""
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

    return " AND ".join(filters), params


async def _filter_addresses(db: AsyncSession, f: BulkFilter) -> list[int]:
    where_sql, params = _build_filter_where(f)

    count = int(
        (
            await db.execute(
                text(f"SELECT COUNT(*) FROM addresses a WHERE {where_sql}"),
                params,
            )
        ).scalar()
        or 0
    )
    if count > _MAX_BULK_AFFECTED:
        raise_error(
            422,
            "BULK_LIMIT_EXCEEDED",
            f"Filter matches {count} addresses (max {_MAX_BULK_AFFECTED}). Narrow your filter.",
        )

    rows = await db.execute(
        text(f"SELECT a.rc_code FROM addresses a WHERE {where_sql} ORDER BY a.rc_code"),
        params,
    )
    return [row[0] for row in rows.all()]


async def _build_sample(
    db: AsyncSession,
    rc_codes: list[int],
    op: AddOfferingOperation | ChangeOfferingOperation | RemoveOfferingOperation,
) -> list[BulkSampleItem]:
    if not rc_codes:
        return []

    addr_sql = text(f"""
        SELECT a.rc_code, {_FULL_ADDRESS} AS full_address
        FROM addresses a {_ADDR_JOINS}
        WHERE a.rc_code = ANY(:codes)
    """)
    addr_rows = {
        r["rc_code"]: r["full_address"]
        for r in (await db.execute(addr_sql, {"codes": rc_codes})).mappings().all()
    }

    existing_sql = text("""
        SELECT address_code, status, max_download_mbps, max_upload_mbps
        FROM address_offerings
        WHERE address_code = ANY(:codes) AND technology_id = CAST(:tech_id AS uuid)
    """)
    existing = {
        r["address_code"]: {
            "status": r["status"],
            "max_dl_mbps": r["max_download_mbps"],
            "max_ul_mbps": r["max_upload_mbps"],
        }
        for r in (
            await db.execute(existing_sql, {"codes": rc_codes, "tech_id": str(op.technology_id)})
        )
        .mappings()
        .all()
    }

    # Build new_state preview based on operation type
    if op.type == "add_offering":
        new_state: dict = {
            "status": op.status,
            "max_dl_mbps": op.max_dl_mbps,
            "max_ul_mbps": op.max_ul_mbps,
            "status_since": str(op.status_since),
        }
    elif op.type == "change_offering":
        new_state = {"_action": "change"}
        if op.new_status is not None:
            new_state["status"] = op.new_status
        if op.new_max_dl_mbps is not None:
            new_state["max_dl_mbps"] = op.new_max_dl_mbps
        if op.new_max_ul_mbps is not None:
            new_state["max_ul_mbps"] = op.new_max_ul_mbps
        if op.new_status_since is not None:
            new_state["status_since"] = str(op.new_status_since)
        if op.new_planned_until is not None:
            new_state["planned_until"] = str(op.new_planned_until)
    else:  # remove_offering
        new_state = {"_action": "delete"}

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
    # Filter out addresses soft-deleted between preview and execute
    live_result = await db.execute(
        select(Address.rc_code).where(
            Address.rc_code.in_(rc_codes),
            Address.deleted_at.is_(None),
        )
    )
    live_rc_codes = [row[0] for row in live_result.fetchall()]
    if not live_rc_codes:
        return []

    current = now()
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
            "created_at": current,
            "updated_at": current,
        }
        for rc in live_rc_codes
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


async def _execute_change_offering(
    db: AsyncSession,
    bulk_op_id: uuid.UUID,
    user_id: uuid.UUID,
    op: ChangeOfferingOperation,
    rc_codes: list[int],
) -> tuple[list[int], list[dict]]:
    """Update existing address_offerings for the given technology. Returns (modified_rc_codes, old_values)."""
    # Fetch existing offerings to capture old values for rollback
    existing = (await db.execute(
        text("""
            SELECT address_code, status, max_download_mbps, max_upload_mbps,
                   status_since, planned_until, notes
            FROM address_offerings
            WHERE address_code = ANY(:codes)
              AND technology_id = CAST(:tech_id AS uuid)
        """),
        {"codes": rc_codes, "tech_id": str(op.technology_id)},
    )).mappings().all()

    if not existing:
        return [], []

    old_values = [
        {
            "address_code": r["address_code"],
            "status": r["status"],
            "max_download_mbps": r["max_download_mbps"],
            "max_upload_mbps": r["max_upload_mbps"],
            "status_since": r["status_since"].isoformat() if r["status_since"] else None,
            "planned_until": r["planned_until"].isoformat() if r["planned_until"] else None,
            "notes": r["notes"],
        }
        for r in existing
    ]
    modified_codes = [int(r["address_code"]) for r in existing]

    # Build dynamic UPDATE — only set fields that are not None
    set_parts = []
    params: dict = {"codes": modified_codes, "tech_id": str(op.technology_id)}
    if op.new_status is not None:
        set_parts.append("status = :status")
        params["status"] = op.new_status
    if op.new_max_dl_mbps is not None:
        set_parts.append("max_download_mbps = :max_dl")
        params["max_dl"] = op.new_max_dl_mbps
    if op.new_max_ul_mbps is not None:
        set_parts.append("max_upload_mbps = :max_ul")
        params["max_ul"] = op.new_max_ul_mbps
    if op.new_status_since is not None:
        set_parts.append("status_since = :ssince")
        params["ssince"] = op.new_status_since
    if op.new_planned_until is not None:
        set_parts.append("planned_until = :punt")
        params["punt"] = op.new_planned_until
    if op.new_notes is not None:
        set_parts.append("notes = :notes")
        params["notes"] = op.new_notes

    if set_parts:
        set_parts.append("updated_at = NOW()")
        sql = text(f"""
            UPDATE address_offerings
            SET {", ".join(set_parts)}
            WHERE address_code = ANY(:codes)
              AND technology_id = CAST(:tech_id AS uuid)
        """)
        await db.execute(sql, params)

    return modified_codes, old_values


async def _execute_remove_offering(
    db: AsyncSession,
    bulk_op_id: uuid.UUID,
    user_id: uuid.UUID,
    op: RemoveOfferingOperation,
    rc_codes: list[int],
) -> tuple[list[int], list[dict]]:
    """Delete existing address_offerings. Returns (deleted_rc_codes, full_data_for_rollback)."""
    existing = (await db.execute(
        text("""
            SELECT address_code, status, max_download_mbps, max_upload_mbps,
                   status_since, planned_until, notes, created_by
            FROM address_offerings
            WHERE address_code = ANY(:codes)
              AND technology_id = CAST(:tech_id AS uuid)
        """),
        {"codes": rc_codes, "tech_id": str(op.technology_id)},
    )).mappings().all()

    if not existing:
        return [], []

    deleted_data = [
        {
            "address_code": r["address_code"],
            "status": r["status"],
            "max_download_mbps": r["max_download_mbps"],
            "max_upload_mbps": r["max_upload_mbps"],
            "status_since": r["status_since"].isoformat() if r["status_since"] else None,
            "planned_until": r["planned_until"].isoformat() if r["planned_until"] else None,
            "notes": r["notes"],
            "created_by": str(r["created_by"]),
        }
        for r in existing
    ]
    deleted_codes = [int(r["address_code"]) for r in existing]

    await db.execute(
        text("""
            DELETE FROM address_offerings
            WHERE address_code = ANY(:codes)
              AND technology_id = CAST(:tech_id AS uuid)
        """),
        {"codes": deleted_codes, "tech_id": str(op.technology_id)},
    )

    return deleted_codes, deleted_data


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


async def _consume_token(token: str, user_id: uuid.UUID, db: AsyncSession) -> dict:
    result = await db.execute(
        select(BulkPreviewToken).where(BulkPreviewToken.token == token)
    )
    token_row = result.scalar_one_or_none()
    if token_row is None:
        raise HTTPException(status_code=422, detail="Invalid or expired preview token")
    if token_row.user_id != user_id:
        raise HTTPException(status_code=403, detail="Preview token belongs to a different user")
    if now() > token_row.expires_at:
        await db.delete(token_row)
        await db.flush()
        raise HTTPException(status_code=422, detail="Preview token expired (5 min limit)")
    payload = dict(token_row.payload)
    await db.delete(token_row)
    await db.flush()
    return payload
