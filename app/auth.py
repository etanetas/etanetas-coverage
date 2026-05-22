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
    current = now()
    result = await db.execute(
        select(ApiKey, User)
        .join(User, ApiKey.user_id == User.id)
        .where(
            ApiKey.revoked_at.is_(None),
            or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > current),
            User.active.is_(True),
        )
    )
    rows = result.all()

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
            return user

    raise HTTPException(status_code=401, detail="Invalid or missing API key")
