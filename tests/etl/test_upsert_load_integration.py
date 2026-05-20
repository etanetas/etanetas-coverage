"""Integration tests for upsert_load — requires running DB with migrations applied.

Note: upsert_all() calls session.commit() internally, so the db_session rollback
fixture cannot clean up this test data. We use a dedicated cleanup fixture instead.
Test counties use rc_codes >= 9000 to avoid collisions with real LT data (codes 1-10).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.address import County
from etl.loaders.upsert_load import upsert_all

_TEST_RC_MIN = 9000


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def _county_rows(*entries):
    return [{"rc_code": rc, "name": name, "synced_at": _now()} for rc, name in entries]


async def _aiter(items):
    for item in items:
        yield item


@pytest.fixture(autouse=True)
async def cleanup_test_counties():
    """Delete all test counties (rc_code >= 9000) after each test."""
    yield
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        await session.execute(delete(County).where(County.rc_code >= _TEST_RC_MIN))
        await session.commit()
    await engine.dispose()


@pytest.mark.integration
class TestUpsertAll:
    async def test_insert_new_rows(self, db_session):
        rows = _county_rows((9901, "TestCounty A"), (9902, "TestCounty B"))
        n = await upsert_all(db_session, County, _aiter(rows))
        assert n == 2

    async def test_rows_visible_in_same_session(self, db_session):
        rows = _county_rows((9903, "TestCounty C"))
        await upsert_all(db_session, County, _aiter(rows))
        result = await db_session.scalar(select(County).where(County.rc_code == 9903))
        assert result is not None
        assert result.name == "TestCounty C"

    async def test_upsert_updates_existing(self, db_session):
        rows = _county_rows((9904, "Original Name"))
        await upsert_all(db_session, County, _aiter(rows))
        updated = _county_rows((9904, "Updated Name"))
        await upsert_all(db_session, County, _aiter(updated))
        result = await db_session.scalar(select(County).where(County.rc_code == 9904))
        assert result.name == "Updated Name"

    async def test_empty_input_returns_zero(self, db_session):
        n = await upsert_all(db_session, County, _aiter([]))
        assert n == 0

    async def test_large_batch_chunked_correctly(self, db_session):
        rows = _county_rows(*((9000 + i, f"County {i}") for i in range(200)))
        n = await upsert_all(db_session, County, _aiter(rows), batch_size=50)
        assert n == 200
