"""Integration tests for state_db — requires running DB with migrations applied.

Note: state_db functions call session.commit() internally, so the db_session
rollback fixture cannot clean up this test data. We restore the original state
after each test using a dedicated fixture.
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from etl.state_db import (
    _CID_KEY,
    _LAST_SYNC_KEY,
    _STEP_KEY,
    _get,
    _set,
    clear_import_progress,
    get_completed_step,
    get_last_cid,
    get_last_nightly_sync_date,
    save_cid,
    save_completed_step,
    save_nightly_sync_date,
)


@pytest.fixture(autouse=True)
async def restore_etl_state():
    """Snapshot etl_state before test, restore after."""
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        original = {
            _CID_KEY: await _get(session, _CID_KEY),
            _STEP_KEY: await _get(session, _STEP_KEY),
            _LAST_SYNC_KEY: await _get(session, _LAST_SYNC_KEY),
        }

    yield

    async with Session() as session:
        for key, value in original.items():
            if value is not None:
                await _set(session, key, value)
            # if key didn't exist before, leave whatever the test set
            # (deleting would need raw SQL — acceptable tradeoff)

    await engine.dispose()


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
        assert result is None or isinstance(result, str)

    async def test_save_records_today(self, db_session):
        from datetime import date

        await save_nightly_sync_date(db_session)
        result = await get_last_nightly_sync_date(db_session)
        assert result == date.today().isoformat()
