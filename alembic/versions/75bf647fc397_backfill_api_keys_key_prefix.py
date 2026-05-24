"""backfill api_keys.key_prefix

Revision ID: 75bf647fc397
Revises: a72a12d9c895
Create Date: 2026-05-22 12:56:56.028626

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '75bf647fc397'
down_revision: str | Sequence[str] | None = 'a72a12d9c895'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # key_hash is bcrypt — we can't recover the raw key. Mark legacy rows with a
    # sentinel so the fast path SKIPS them (and slow fallback scans them once).
    op.execute("UPDATE api_keys SET key_prefix = '__legacy__' WHERE key_prefix IS NULL")


def downgrade() -> None:
    op.execute("UPDATE api_keys SET key_prefix = NULL WHERE key_prefix = '__legacy__'")
