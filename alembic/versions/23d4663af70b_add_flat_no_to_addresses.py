"""add flat_no to addresses

Revision ID: 23d4663af70b
Revises: 2608c0c3d364
Create Date: 2026-05-20 13:11:24.558778

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "23d4663af70b"
down_revision: str | Sequence[str] | None = "2608c0c3d364"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("addresses", sa.Column("flat_no", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("addresses", "flat_no")
