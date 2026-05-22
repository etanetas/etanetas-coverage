"""technologies: add deleted_at, drop active

Revision ID: a72a12d9c895
Revises: cc7f18b34d4a
Create Date: 2026-05-22 12:44:58.002941

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a72a12d9c895'
down_revision: Union[str, Sequence[str], None] = 'cc7f18b34d4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # technologies
    op.add_column("technologies", sa.Column("deleted_at", sa.DateTime(timezone=False), nullable=True))
    op.execute("UPDATE technologies SET deleted_at = NOW() WHERE active = false")
    op.drop_column("technologies", "active")

    # technology_types
    op.add_column("technology_types", sa.Column("deleted_at", sa.DateTime(timezone=False), nullable=True))
    op.execute("UPDATE technology_types SET deleted_at = NOW() WHERE active = false")
    op.drop_column("technology_types", "active")


def downgrade() -> None:
    op.add_column("technology_types", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.execute("UPDATE technology_types SET active = false WHERE deleted_at IS NOT NULL")
    op.drop_column("technology_types", "deleted_at")

    op.add_column("technologies", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.execute("UPDATE technologies SET active = false WHERE deleted_at IS NOT NULL")
    op.drop_column("technologies", "deleted_at")
