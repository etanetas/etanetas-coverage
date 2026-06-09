"""Helper functions for audit log diff enrichment.

Provide human-readable labels for rc_code and technology_id values stored in
audit log diff entries.
"""

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.address_labels import _ADDR_JOINS, _FULL_ADDRESS


async def address_label_for_code(db: AsyncSession, rc_code: int) -> str | None:
    """Return a human-readable address label for the given rc_code, or None if not found."""
    result = await db.execute(
        text(
            f"SELECT {_FULL_ADDRESS} AS label FROM addresses a {_ADDR_JOINS} WHERE a.rc_code = :rc_code"
        ),
        {"rc_code": rc_code},
    )
    row = result.one_or_none()
    return row[0] if row else None


async def technology_display_name(db: AsyncSession, technology_id: uuid.UUID) -> str | None:
    """Return the display_name for the given technology UUID, or None if not found."""
    from app.models.technology import Technology

    result = await db.execute(
        select(Technology.display_name).where(Technology.id == technology_id)
    )
    return result.scalar_one_or_none()
