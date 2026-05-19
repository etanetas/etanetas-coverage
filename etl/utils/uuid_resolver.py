"""Caching UUID → integer code resolver for Spinta lookups.

Used during nightly_sync to translate change-record UUIDs (e.g. ``aob_kodas._id``)
to our integer rc_codes (e.g. ``aob_kodas``).
"""

import logging

from etl.downloaders.spinta_client import SpintaClient

log = logging.getLogger(__name__)


class UUIDResolver:
    """Translate Spinta UUIDs to integer codes, with in-memory cache.

    Each ``resolve_*`` method calls Spinta once per unique UUID; subsequent calls
    return cached result. Failures are logged as WARNING and return ``None``.
    """

    def __init__(self, spinta: SpintaClient):
        self._spinta = spinta
        self._cache: dict[tuple[str, str], int] = {}

    async def _resolve(self, model: str, uuid: str, int_field: str) -> int | None:
        """Fetch :uuid: from :model:, extract :int_field:. Cached. None on failure."""
        key = (model, uuid)
        if key in self._cache:
            return self._cache[key]
        try:
            record = await self._spinta.fetch_one(model, uuid)
        except Exception as exc:
            log.warning("UUID resolution failed for %s/%s: %s", model, uuid, exc)
            return None
        if not record or int_field not in record:
            log.warning("Could not resolve %s/%s — field %s missing", model, uuid, int_field)
            return None
        try:
            value = int(record[int_field])
        except (TypeError, ValueError) as exc:
            log.warning("Field %s in %s/%s is not an int: %s", int_field, model, uuid, exc)
            return None
        self._cache[key] = value
        return value

    async def resolve_aob(self, uuid: str) -> int | None:
        """Resolve adresai/Adresas UUID → ``aob_kodas`` integer."""
        return await self._resolve("adresai/Adresas", uuid, "aob_kodas")

    async def resolve_gatve(self, uuid: str) -> int | None:
        """Resolve gatve/Gatve UUID → ``gat_kodas`` integer."""
        return await self._resolve("gatve/Gatve", uuid, "gat_kodas")

    async def resolve_gyv(self, uuid: str) -> int | None:
        """Resolve gyvenamojivietove/GyvenamojiVietove UUID → ``gyv_kodas`` integer."""
        return await self._resolve("gyvenamojivietove/GyvenamojiVietove", uuid, "gyv_kodas")
