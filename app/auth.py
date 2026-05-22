import asyncio
import logging
import uuid
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.dependencies import get_db
from app.models.admin import ApiKey, User
from app.time import now

# Hold strong refs to background tasks so GC doesn't cancel them.
_background_tasks: set[asyncio.Task] = set()

log = logging.getLogger(__name__)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


async def _update_last_used(key_id: uuid.UUID) -> None:
    """Best-effort timestamp update — scheduled via BackgroundTasks after response."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(ApiKey).where(ApiKey.id == key_id).values(last_used_at=now())
            )
            await session.commit()
    except SQLAlchemyError as exc:
        log.warning("Failed to update last_used_at for key %s: %s", key_id, exc)


async def _set_prefix(api_key_id: uuid.UUID, prefix: str) -> None:
    """Best-effort backfill of key_prefix on a legacy row after successful match."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(ApiKey).where(ApiKey.id == api_key_id).values(key_prefix=prefix)
            )
            await session.commit()
    except SQLAlchemyError as exc:
        log.warning("Failed to backfill prefix for key %s: %s", api_key_id, exc)


def require_role(*roles: str):
    """Dependency factory: checks that the authenticated user has one of the given roles."""
    async def _check(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return _check


async def get_current_user(
    raw_key: Annotated[str, Security(_api_key_header)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if not raw_key or not raw_key.startswith("etn_pk_"):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    current = now()
    prefix = raw_key[:11]

    async def _candidates(filter_prefix: str):
        return (await db.execute(
            select(ApiKey, User)
            .join(User, ApiKey.user_id == User.id)
            .where(
                ApiKey.key_prefix == filter_prefix,
                ApiKey.revoked_at.is_(None),
                or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > current),
                User.active.is_(True),
            )
        )).all()

    rows = await _candidates(prefix)
    if not rows:
        # Legacy fallback: scan rows still marked __legacy__ (shrinking set).
        rows = await _candidates("__legacy__")

    for api_key, user in rows:
        if bcrypt.checkpw(raw_key.encode(), api_key.key_hash.encode()):
            # Throttle: only spawn an update task if last_used_at is >60s ago (or NULL)
            if (
                api_key.last_used_at is None
                or (current - api_key.last_used_at).total_seconds() > 60
            ):
                task = asyncio.create_task(_update_last_used(api_key.id))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            # Opportunistic prefix migration for legacy rows
            if api_key.key_prefix == "__legacy__":
                task2 = asyncio.create_task(_set_prefix(api_key.id, prefix))
                _background_tasks.add(task2)
                task2.add_done_callback(_background_tasks.discard)
            return user

    raise HTTPException(status_code=401, detail="Invalid or missing API key")
