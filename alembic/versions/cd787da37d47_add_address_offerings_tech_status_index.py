"""add address_offerings tech status index

Revision ID: cd787da37d47
Revises: c76434df3e06
Create Date: 2026-06-11 09:59:06.089752

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'cd787da37d47'
down_revision: str | Sequence[str] | None = 'c76434df3e06'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "idx_address_offerings_tech_available",
        "address_offerings",
        ["technology_id"],
        postgresql_where=sa.text("status = 'available'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_address_offerings_tech_available", table_name="address_offerings")
