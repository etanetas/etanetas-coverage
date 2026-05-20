"""Incremental loader — applies Spinta change records to the ``addresses`` table.

Two entry points:
 - ``apply_adresas_changes``: handles deletes from ``adresai/Adresas/:changes``
 - ``apply_pastatas_changes``: handles inserts/updates/deletes from ``pastatas/Pastatas/:changes``

New addresses inserted by nightly_sync get ``point=NULL``; monthly_full_resync fills them
when the GeoJSON refreshes.
"""

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.address import Address
from etl.downloaders.spinta_client import SpintaClient
from etl.utils.time import utcnow_naive
from etl.utils.uuid_resolver import UUIDResolver

log = logging.getLogger(__name__)


async def apply_adresas_changes(
    session: AsyncSession,
    changes: list[dict[str, Any]],
) -> int:
    """Apply ``adresai/Adresas`` change records. Returns count of addresses marked deleted.

    Only ``delete``/``remove`` ops are handled here — inserts in this stream don't carry
    enough info (no house_no/street/locality). The corresponding inserts come via the
    ``pastatas/Pastatas`` change stream.
    """
    deleted = 0
    for rec in changes:
        if rec["_op"] not in ("delete", "remove"):
            continue
        try:
            result = await session.execute(
                text(
                    "UPDATE addresses SET deleted_at = :now "
                    "WHERE rc_code = :rc AND deleted_at IS NULL"
                ),
                {"now": utcnow_naive(), "rc": rec["aob_kodas"]},
            )
            deleted += result.rowcount
        except Exception as exc:
            log.error("Failed to mark aob_kodas=%s as deleted: %s", rec.get("aob_kodas"), exc)
            continue
    await session.commit()
    return deleted


async def apply_pastatas_changes(
    session: AsyncSession,
    spinta: SpintaClient,
    changes: list[dict[str, Any]],
) -> tuple[int, int]:
    """Apply ``pastatas/Pastatas`` change records. Returns ``(upserted, deleted)`` counts.

    UUIDs in change records (aob_kodas._id, gatve._id, gyvenamoji_vietove._id) are resolved
    to integer rc_codes via Spinta lookups (cached in-memory by ``UUIDResolver``).
    """
    resolver = UUIDResolver(spinta)
    upserted = 0
    deleted = 0

    for rec in changes:
        op = rec["_op"]
        aob_uuid = rec.get("aob_kodas", {}).get("_id") if rec.get("aob_kodas") else None
        if not aob_uuid:
            continue

        if op in ("delete", "remove"):
            rc_code = await resolver.resolve_aob(aob_uuid)
            if rc_code is None:
                continue
            try:
                await session.execute(
                    text(
                        "UPDATE addresses SET deleted_at = :now "
                        "WHERE rc_code = :rc AND deleted_at IS NULL"
                    ),
                    {"now": utcnow_naive(), "rc": rc_code},
                )
                deleted += 1
            except Exception as exc:
                log.error("Failed to mark rc_code=%d as deleted: %s", rc_code, exc)
                continue

        elif op in ("insert", "update", "patch"):
            row = await _build_address_row(rec, resolver, aob_uuid)
            if row is None:
                continue
            try:
                stmt = pg_insert(Address).values([row])
                provided = set(row.keys()) - {"rc_code"}
                update_cols = {c.name: c for c in stmt.excluded if c.name in provided}
                stmt = stmt.on_conflict_do_update(index_elements=["rc_code"], set_=update_cols)
                await session.execute(stmt)
                upserted += 1
            except Exception as exc:
                log.error("Failed to upsert address rc_code=%d: %s", row["rc_code"], exc)
                continue

    await session.commit()
    return upserted, deleted


async def _build_address_row(
    rec: dict[str, Any],
    resolver: UUIDResolver,
    aob_uuid: str,
) -> dict[str, Any] | None:
    """Resolve UUIDs from a pastatas change record and build an Address row dict.

    Returns ``None`` if the record is incomplete (missing ``nr``, unresolvable UUIDs).
    Logs a WARNING in each case.
    """
    if not rec.get("nr"):
        return None

    rc_code = await resolver.resolve_aob(aob_uuid)
    if rc_code is None:
        log.warning("cannot resolve aob_uuid %s — skipping", aob_uuid)
        return None

    gyv_uuid = (
        rec.get("gyvenamoji_vietove", {}).get("_id") if rec.get("gyvenamoji_vietove") else None
    )
    if not gyv_uuid:
        return None
    locality_code = await resolver.resolve_gyv(gyv_uuid)
    if locality_code is None:
        log.warning("cannot resolve gyv_uuid %s — skipping", gyv_uuid)
        return None

    gatve_uuid = rec.get("gatve", {}).get("_id") if rec.get("gatve") else None
    street_code: int | None = None
    if gatve_uuid:
        street_code = await resolver.resolve_gatve(gatve_uuid)

    return {
        "rc_code": rc_code,
        "street_code": street_code,
        "locality_code": locality_code,
        "house_no": rec["nr"],
        "postal_code": rec.get("pasto_kodas") or None,
        "point": None,  # filled by monthly_full_resync when GeoJSON refreshes
        "synced_at": utcnow_naive(),
        "deleted_at": None,
    }
