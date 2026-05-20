import bcrypt
import secrets
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.auth import get_current_user, require_role
from app.dependencies import get_db
from app.models.admin import ApiKey, User
from app.schemas.admin import ApiKeyCreate, ApiKeyCreated, ApiKeyOut, UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/me", response_model=UserOut)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user


@router.get("/users", response_model=list[UserOut])
async def list_users(
    current_user: Annotated[User, Depends(require_role("admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[User]:
    result = await db.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


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
    now = datetime.now()
    for key in keys.scalars().all():
        key.revoked_at = now

    await db.commit()


@router.get("/users/{user_id}/api-keys", response_model=list[ApiKeyOut])
async def list_api_keys(
    user_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role("admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ApiKey]:
    await _require_user(db, user_id)
    result = await db.execute(
        select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.created_at)
    )
    return list(result.scalars().all())


@router.post("/users/{user_id}/api-keys", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(
    user_id: uuid.UUID,
    body: ApiKeyCreate,
    current_user: Annotated[User, Depends(require_role("admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiKeyCreated:
    await _require_user(db, user_id)

    raw_key = "etn_pk_" + secrets.token_urlsafe(32)
    key_hash = bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt()).decode()

    api_key = ApiKey(user_id=user_id, key_hash=key_hash, name=body.name)
    db.add(api_key)
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

    key.revoked_at = datetime.now()
    await db.commit()


async def _require_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user
