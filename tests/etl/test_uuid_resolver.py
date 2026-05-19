"""Unit tests for etl.utils.uuid_resolver."""

from unittest.mock import AsyncMock

from etl.utils.uuid_resolver import UUIDResolver


def _mock_spinta(**fetch_one_map):
    """Create a SpintaClient mock where fetch_one returns mapped values."""
    spinta = AsyncMock()

    async def _fetch_one(model, uuid):
        return fetch_one_map.get(uuid)

    spinta.fetch_one = _fetch_one
    return spinta


class TestUUIDResolver:
    async def test_resolve_returns_int_from_spinta(self):
        spinta = _mock_spinta(**{"some-uuid": {"aob_kodas": 12345}})
        resolver = UUIDResolver(spinta)
        result = await resolver.resolve_aob("some-uuid")
        assert result == 12345

    async def test_cache_avoids_repeated_fetch(self):
        call_count = 0

        async def counting_fetch_one(model, uuid):
            nonlocal call_count
            call_count += 1
            return {"aob_kodas": 999}

        spinta = AsyncMock()
        spinta.fetch_one = counting_fetch_one
        resolver = UUIDResolver(spinta)

        await resolver.resolve_aob("same-uuid")
        await resolver.resolve_aob("same-uuid")
        await resolver.resolve_aob("same-uuid")

        assert call_count == 1

    async def test_returns_none_when_not_found(self):
        spinta = _mock_spinta()  # no mappings → all return None
        resolver = UUIDResolver(spinta)
        result = await resolver.resolve_aob("missing")
        assert result is None

    async def test_returns_none_when_field_missing(self):
        spinta = _mock_spinta(**{"u1": {"other_field": 1}})
        resolver = UUIDResolver(spinta)
        result = await resolver.resolve_aob("u1")
        assert result is None

    async def test_returns_none_when_spinta_raises(self):
        async def broken_fetch_one(model, uuid):
            raise RuntimeError("network error")

        spinta = AsyncMock()
        spinta.fetch_one = broken_fetch_one
        resolver = UUIDResolver(spinta)
        result = await resolver.resolve_aob("u1")
        assert result is None

    async def test_different_models_have_separate_cache(self):
        async def fetch_one(model, uuid):
            if model == "adresai/Adresas":
                return {"aob_kodas": 111}
            elif model == "gatve/Gatve":
                return {"gat_kodas": 222}
            elif model == "gyvenamojivietove/GyvenamojiVietove":
                return {"gyv_kodas": 333}
            return None

        spinta = AsyncMock()
        spinta.fetch_one = fetch_one
        resolver = UUIDResolver(spinta)

        assert await resolver.resolve_aob("u1") == 111
        assert await resolver.resolve_gatve("u1") == 222
        assert await resolver.resolve_gyv("u1") == 333

    async def test_resolve_returns_none_on_non_int_value(self):
        spinta = _mock_spinta(**{"u1": {"aob_kodas": "not-a-number"}})
        resolver = UUIDResolver(spinta)
        result = await resolver.resolve_aob("u1")
        assert result is None
