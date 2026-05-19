"""Unit tests for incremental_load — apply_adresas_changes and apply_pastatas_changes.

Uses MagicMock for DB session and SpintaClient to avoid real network/DB calls.
"""

from unittest.mock import AsyncMock, MagicMock

from etl.loaders.incremental_load import apply_adresas_changes, apply_pastatas_changes


def _make_session():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    session.commit = AsyncMock()
    return session


def _make_spinta(**fetch_one_map):
    """Returns a mock SpintaClient where fetch_one returns values from the map."""
    spinta = AsyncMock()

    async def _fetch_one(model, uuid):
        return fetch_one_map.get(uuid)

    spinta.fetch_one = _fetch_one
    return spinta


class TestApplyAdresasChanges:
    async def test_delete_calls_update(self):
        session = _make_session()
        changes = [{"_op": "delete", "_cid": 1, "aob_kodas": 12345}]
        deleted = await apply_adresas_changes(session, changes)
        assert deleted == 1
        session.execute.assert_called_once()
        call_args = session.execute.call_args
        # Verify the SQL has deleted_at update
        assert "deleted_at" in str(call_args[0][0])

    async def test_insert_not_handled(self):
        session = _make_session()
        changes = [{"_op": "insert", "_cid": 2, "aob_kodas": 99999}]
        deleted = await apply_adresas_changes(session, changes)
        assert deleted == 0
        session.execute.assert_not_called()

    async def test_remove_op_also_deletes(self):
        session = _make_session()
        changes = [{"_op": "remove", "_cid": 3, "aob_kodas": 111}]
        deleted = await apply_adresas_changes(session, changes)
        assert deleted == 1

    async def test_empty_changes(self):
        session = _make_session()
        deleted = await apply_adresas_changes(session, [])
        assert deleted == 0
        session.commit.assert_called_once()


class TestApplyPastatasChanges:
    def _aob_uuid(self):
        return "aob-uuid-111"

    def _gyv_uuid(self):
        return "gyv-uuid-456"

    def _gat_uuid(self):
        return "gat-uuid-789"

    def _insert_record(self, nr="14", include_street=True):
        rec = {
            "_op": "insert",
            "_cid": 10,
            "aob_kodas": {"_id": self._aob_uuid()},
            "gyvenamoji_vietove": {"_id": self._gyv_uuid()},
            "nr": nr,
            "pasto_kodas": "LT-01234",
        }
        if include_street:
            rec["gatve"] = {"_id": self._gat_uuid()}
        return rec

    def _make_spinta_with_lookups(self):
        return _make_spinta(
            **{
                self._aob_uuid(): {"aob_kodas": 155218235},
                self._gyv_uuid(): {"gyv_kodas": 21768},
                self._gat_uuid(): {"gat_kodas": 1198812},
            }
        )

    async def test_insert_upserts_address(self):
        session = _make_session()
        spinta = self._make_spinta_with_lookups()
        changes = [self._insert_record()]
        upserted, deleted = await apply_pastatas_changes(session, spinta, changes)
        assert upserted == 1
        assert deleted == 0
        session.execute.assert_called_once()

    async def test_insert_without_nr_skipped(self):
        session = _make_session()
        spinta = self._make_spinta_with_lookups()
        changes = [self._insert_record(nr="")]
        upserted, deleted = await apply_pastatas_changes(session, spinta, changes)
        assert upserted == 0

    async def test_insert_no_street_still_upserts(self):
        session = _make_session()
        spinta = self._make_spinta_with_lookups()
        changes = [self._insert_record(include_street=False)]
        upserted, deleted = await apply_pastatas_changes(session, spinta, changes)
        assert upserted == 1

    async def test_delete_marks_deleted_at(self):
        session = _make_session()
        spinta = _make_spinta(**{self._aob_uuid(): {"aob_kodas": 155218235}})
        changes = [{"_op": "delete", "_cid": 5, "aob_kodas": {"_id": self._aob_uuid()}}]
        upserted, deleted = await apply_pastatas_changes(session, spinta, changes)
        assert deleted == 1
        assert upserted == 0

    async def test_unresolvable_aob_uuid_skipped(self):
        session = _make_session()
        spinta = _make_spinta()  # no mappings — all fetch_one return None
        changes = [self._insert_record()]
        upserted, deleted = await apply_pastatas_changes(session, spinta, changes)
        assert upserted == 0

    async def test_uuid_cache_reused(self):
        """Same UUID in two records should only call fetch_one once."""
        session = _make_session()
        call_count = 0

        async def counting_fetch_one(model, uuid):
            nonlocal call_count
            call_count += 1
            mapping = {
                self._aob_uuid(): {"aob_kodas": 123},
                self._gyv_uuid(): {"gyv_kodas": 456},
                self._gat_uuid(): {"gat_kodas": 789},
            }
            return mapping.get(uuid)

        spinta = AsyncMock()
        spinta.fetch_one = counting_fetch_one

        changes = [self._insert_record(), self._insert_record(nr="15")]
        await apply_pastatas_changes(session, spinta, changes)
        # 3 unique UUIDs (aob, gyv, gat) — each fetched once despite 2 records
        assert call_count == 3

    async def test_empty_changes(self):
        session = _make_session()
        spinta = AsyncMock()
        upserted, deleted = await apply_pastatas_changes(session, spinta, [])
        assert upserted == 0
        assert deleted == 0
        session.commit.assert_called_once()
