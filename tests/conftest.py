"""Shared pytest fixtures.

db_session: async SQLAlchemy session wrapped in a rolled-back transaction.
Each test gets a clean slate — no data leaks between tests.
Requires a running PostgreSQL+PostGIS instance with migrations applied.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def db_session() -> AsyncSession:
    """Async DB session that rolls back after each test."""
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        await session.begin()
        try:
            yield session
        finally:
            await session.rollback()

    await engine.dispose()
