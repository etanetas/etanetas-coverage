import asyncio
import os

import geoalchemy2
from dotenv import load_dotenv
from geoalchemy2 import alembic_helpers
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.models import Base

load_dotenv()

config = context.config
target_metadata = Base.metadata

# Indexes created via raw SQL (DESC ordering) — autogenerate cannot represent them
# correctly in models, so we exclude them from comparison.
_RAW_SQL_INDEXES = frozenset({"idx_bulk_operations_created", "idx_audit_log_at"})


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "index" and name in _RAW_SQL_INDEXES:
        return False
    if not alembic_helpers.include_object(object, name, type_, reflected, compare_to):
        return False
    if type_ == "table" and reflected and compare_to is None:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=os.environ["DATABASE_URL"],
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        process_revision_directives=alembic_helpers.writer,
        render_item=alembic_helpers.render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        process_revision_directives=alembic_helpers.writer,
        render_item=alembic_helpers.render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
