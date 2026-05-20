"""
API test fixtures.

db_session here patches commit() → flush() so endpoint handlers that call
db.commit() don't actually commit the outer test transaction. Data written by
the handler is still visible within the same session (flush sends SQL to the
DB but stays inside the open transaction), and the whole thing rolls back at
the end of each test.

This fixture shadows the top-level conftest db_session for tests under tests/api/.
ETL tests are unaffected.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        await session.begin()
        session.commit = session.flush  # type: ignore[method-assign]
        try:
            yield session
        finally:
            await session.rollback()

    await engine.dispose()
