import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import AuditLog
from app.time import now


def _jsonify(obj: Any) -> Any:
    """Recursively convert non-JSON-serializable types to strings."""
    return json.loads(json.dumps(obj, default=str))


async def log_action(
    db: AsyncSession,
    user_id: uuid.UUID,
    entity_type: str,
    entity_id: str,
    action: str,
    diff: dict | None = None,
    address_code: int | None = None,
) -> None:
    """Append an audit entry to the session. The caller must commit."""
    db.add(AuditLog(
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        diff=_jsonify(diff) if diff is not None else None,
        at=now(),
        address_code=address_code,
    ))
