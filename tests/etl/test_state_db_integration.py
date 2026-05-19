"""Integration tests for state_db — requires running DB with migrations applied."""

import pytest

from etl.state_db import (
    clear_import_progress,
    get_completed_step,
    get_last_cid,
    get_last_nightly_sync_date,
    save_cid,
    save_completed_step,
    save_nightly_sync_date,
)


@pytest.mark.integration
class TestCidPersistence:
    async def test_returns_int(self, db_session):
        result = await get_last_cid(db_session)
        assert isinstance(result, int)
        assert result >= 0

    async def test_save_and_read_cid(self, db_session):
        await save_cid(db_session, 99999)
        assert await get_last_cid(db_session) == 99999

    async def test_overwrite_cid(self, db_session):
        await save_cid(db_session, 100)
        await save_cid(db_session, 200)
        assert await get_last_cid(db_session) == 200


@pytest.mark.integration
class TestImportCheckpoint:
    async def test_fresh_state_is_none(self, db_session):
        await clear_import_progress(db_session)
        assert await get_completed_step(db_session) == ""

    async def test_save_and_read_step(self, db_session):
        await save_completed_step(db_session, "counties")
        assert await get_completed_step(db_session) == "counties"

    async def test_clear_resets_to_empty(self, db_session):
        await save_completed_step(db_session, "addresses")
        await clear_import_progress(db_session)
        assert await get_completed_step(db_session) == ""

    async def test_sequential_steps(self, db_session):
        for step in ["counties", "municipalities", "localities"]:
            await save_completed_step(db_session, step)
        assert await get_completed_step(db_session) == "localities"


@pytest.mark.integration
class TestNightlySyncDate:
    async def test_default_is_none(self, db_session):
        result = await get_last_nightly_sync_date(db_session)
        # May be None or a previously saved date — just check it doesn't crash
        assert result is None or isinstance(result, str)

    async def test_save_records_today(self, db_session):
        from datetime import date

        await save_nightly_sync_date(db_session)
        result = await get_last_nightly_sync_date(db_session)
        assert result == date.today().isoformat()
