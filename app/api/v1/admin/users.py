import bcrypt
import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import Page, PaginationParams, pagination_params
from app.audit import log_action
from app.auth import get_current_user, require_role
from app.config import settings
from app.dependencies import get_db
from app.models.admin import ApiKey, User
from app.schemas.admin import ApiKeyCreate, ApiKeyCreated, ApiKeyOut, UserCreate, UserOut, UserUpdate
from app.time import now

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/me", response_model=UserOut)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user


@router.get("/users", response_model=Page[UserOut])
async def list_users(
    current_user: Annotated[User, Depends(require_role("admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[PaginationParams, Depends(pagination_params)],
    q: Annotated[str | None, Query(description="substring on username/email")] = None,
    role: Annotated[str | None, Query()] = None,
    active: Annotated[bool | None, Query()] = None,
) -> Page[UserOut]:
    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)
    if q:
        like = f"%{q}%"
        cond = or_(User.username.ilike(like), User.email.ilike(like))
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if role:
        stmt = stmt.where(User.role == role)
        count_stmt = count_stmt.where(User.role == role)
    if active is not None:
        stmt = stmt.where(User.active.is_(active))
        count_stmt = count_stmt.where(User.active.is_(active))

    total = int((await db.execute(count_stmt)).scalar() or 0)
    result = await db.execute(stmt.order_by(User.created_at).limit(page.limit).offset(page.offset))
    items = [UserOut.model_validate(u) for u in result.scalars().all()]
    return Page[UserOut](total=total, items=items)


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate,
    current_user: Annotated[User, Depends(require_role("admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Username already exists")

    user = User(username=body.username, email=body.email, role=body.role, active=True)
    db.add(user)
    await db.flush()
    await log_action(db, current_user.id, "user", str(user.id), "create",
                     {"username": body.username, "role": body.role})
    await db.commit()
    await db.refresh(user)
    return user


@router.put("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    current_user: Annotated[User, Depends(require_role("admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    user = await _require_user(db, user_id)

    changes = body.model_dump(exclude_none=True)
    if body.email is not None:
        user.email = body.email
    if body.role is not None:
        user.role = body.role
    if body.active is not None:
        user.active = body.active
    if "lms_username" in changes:
        user.lms_username = body.lms_username  # allow setting to None

    await log_action(db, current_user.id, "user", str(user_id), "update", changes)
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role("admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    user = await _require_user(db, user_id)
    user.active = False
    await log_action(db, current_user.id, "user", str(user_id), "deactivate",
                     {"username": user.username})

    keys = await db.execute(
        select(ApiKey).where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
    )
    current = now()
    for key in keys.scalars().all():
        key.revoked_at = current

    await db.commit()


@router.get("/users/{user_id}/api-keys", response_model=Page[ApiKeyOut])
async def list_api_keys(
    user_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role("admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[PaginationParams, Depends(pagination_params)],
    active_only: Annotated[bool, Query(description="exclude revoked keys")] = False,
) -> Page[ApiKeyOut]:
    await _require_user(db, user_id)
    stmt = select(ApiKey).where(ApiKey.user_id == user_id)
    count_stmt = select(func.count()).select_from(ApiKey).where(ApiKey.user_id == user_id)
    if active_only:
        stmt = stmt.where(ApiKey.revoked_at.is_(None))
        count_stmt = count_stmt.where(ApiKey.revoked_at.is_(None))

    total = int((await db.execute(count_stmt)).scalar() or 0)
    result = await db.execute(stmt.order_by(ApiKey.created_at).limit(page.limit).offset(page.offset))
    items = [ApiKeyOut.model_validate(k) for k in result.scalars().all()]
    return Page[ApiKeyOut](total=total, items=items)


@router.post("/users/{user_id}/api-keys", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(
    user_id: uuid.UUID,
    body: ApiKeyCreate,
    current_user: Annotated[User, Depends(require_role("admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiKeyCreated:
    await _require_user(db, user_id)

    raw_key = "etn_pk_" + secrets.token_urlsafe(32)
    key_prefix = raw_key[:11]
    key_hash = bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt(rounds=settings.bcrypt_rounds)).decode()

    api_key = ApiKey(user_id=user_id, key_hash=key_hash, key_prefix=key_prefix, name=body.name)
    db.add(api_key)
    await db.flush()
    await log_action(
        db, current_user.id, "api_key", str(api_key.id), "create",
        {"user_id": str(user_id), "name": body.name},
    )
    await db.commit()
    await db.refresh(api_key)

    return ApiKeyCreated(
        id=api_key.id,
        name=api_key.name,
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        revoked_at=api_key.revoked_at,
        raw_key=raw_key,
    )


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role("admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    if key.revoked_at is not None:
        raise HTTPException(status_code=409, detail="API key already revoked")

    key.revoked_at = now()
    await log_action(
        db, current_user.id, "api_key", str(key_id), "revoke",
        {"user_id": str(key.user_id), "name": key.name},
    )
    await db.commit()


@router.get("/users/by-lms-username/{lms_username}", response_model=UserOut)
async def get_user_by_lms_username(
    lms_username: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Look up a user by their LMS username — used by the LMS plugin to resolve sessions."""
    result = await db.execute(select(User).where(User.lms_username == lms_username, User.active.is_(True)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="No active user linked to this LMS username")
    return user


async def _require_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user
