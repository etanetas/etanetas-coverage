import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.address import Address
from etl.downloaders.spinta_client import SpintaClient

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def apply_adresas_changes(
    session: AsyncSession,
    changes: list[dict[str, Any]],
) -> int:
    """Handle adresai/Adresas changes. Returns count of deleted addresses."""
    deleted = 0
    for rec in changes:
        if rec["_op"] in ("delete", "remove"):
            result = await session.execute(
                text(
                    "UPDATE addresses SET deleted_at = :now WHERE rc_code = :rc AND deleted_at IS NULL"
                ),
                {"now": _now(), "rc": rec["aob_kodas"]},
            )
            deleted += result.rowcount
    await session.commit()
    return deleted


async def apply_pastatas_changes(
    session: AsyncSession,
    spinta: SpintaClient,
    changes: list[dict[str, Any]],
) -> tuple[int, int]:
    """Handle pastatas/Pastatas changes. Returns (upserted, deleted) counts.

    UUID resolution is done lazily with an in-memory cache to avoid redundant calls.
    New addresses get point=None — filled by monthly_full_resync when GeoJSON is refreshed.
    """
    upserted = 0
    deleted = 0

    aob_cache: dict[str, int] = {}  # aob_uuid → aob_kodas int
    gatve_cache: dict[str, int] = {}  # gatve_uuid → gat_kodas int
    gyv_cache: dict[str, int] = {}  # gyv_uuid → gyv_kodas int

    async def _resolve_aob(uuid: str) -> int | None:
        if uuid not in aob_cache:
            rec = await spinta.fetch_one("adresai/Adresas", uuid)
            if rec:
                aob_cache[uuid] = rec["aob_kodas"]
        return aob_cache.get(uuid)

    async def _resolve_gatve(uuid: str) -> int | None:
        if uuid not in gatve_cache:
            rec = await spinta.fetch_one("gatve/Gatve", uuid)
            if rec:
                gatve_cache[uuid] = rec["gat_kodas"]
        return gatve_cache.get(uuid)

    async def _resolve_gyv(uuid: str) -> int | None:
        if uuid not in gyv_cache:
            rec = await spinta.fetch_one("gyvenamojivietove/GyvenamojiVietove", uuid)
            if rec:
                gyv_cache[uuid] = rec["gyv_kodas"]
        return gyv_cache.get(uuid)

    for rec in changes:
        op = rec["_op"]
        aob_uuid = rec.get("aob_kodas", {}).get("_id") if rec.get("aob_kodas") else None
        if not aob_uuid:
            continue

        if op in ("delete", "remove"):
            rc_code = await _resolve_aob(aob_uuid)
            if rc_code:
                await session.execute(
                    text(
                        "UPDATE addresses SET deleted_at = :now WHERE rc_code = :rc AND deleted_at IS NULL"
                    ),
                    {"now": _now(), "rc": rc_code},
                )
                deleted += 1

        elif op in ("insert", "update", "patch"):
            if not rec.get("nr"):
                continue

            rc_code = await _resolve_aob(aob_uuid)
            if not rc_code:
                log.warning("cannot resolve aob_uuid %s — skipping", aob_uuid)
                continue

            gyv_uuid = (
                rec.get("gyvenamoji_vietove", {}).get("_id")
                if rec.get("gyvenamoji_vietove")
                else None
            )
            if not gyv_uuid:
                continue
            locality_code = await _resolve_gyv(gyv_uuid)
            if not locality_code:
                log.warning("cannot resolve gyv_uuid %s — skipping", gyv_uuid)
                continue

            gatve_uuid = rec.get("gatve", {}).get("_id") if rec.get("gatve") else None
            street_code: int | None = None
            if gatve_uuid:
                street_code = await _resolve_gatve(gatve_uuid)

            row: dict[str, Any] = {
                "rc_code": rc_code,
                "street_code": street_code,
                "locality_code": locality_code,
                "house_no": rec["nr"],
                "postal_code": rec.get("pasto_kodas") or None,
                "point": None,  # filled by monthly_full_resync when GeoJSON refreshes
                "synced_at": _now(),
                "deleted_at": None,
            }
            stmt = pg_insert(Address).values([row])
            provided = set(row.keys()) - {"rc_code"}
            update_cols = {c.name: c for c in stmt.excluded if c.name in provided}
            stmt = stmt.on_conflict_do_update(index_elements=["rc_code"], set_=update_cols)
            await session.execute(stmt)
            upserted += 1

    await session.commit()
    return upserted, deleted
