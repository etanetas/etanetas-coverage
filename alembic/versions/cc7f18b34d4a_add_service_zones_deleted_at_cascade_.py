"""add service_zones.deleted_at + cascade zone_offerings

Revision ID: cc7f18b34d4a
Revises: 6ef10fd18c20
Create Date: 2026-05-22 12:37:46.817296

NOTE: zone_offerings_zone_id_fkey already has ON DELETE CASCADE in the baseline
migration, so no FK drop/recreate is needed here.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "cc7f18b34d4a"
down_revision: Union[str, Sequence[str], None] = "6ef10fd18c20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "service_zones",
        sa.Column("deleted_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.create_index(
        "ix_service_zones_alive",
        "service_zones",
        ["id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_service_zones_alive", table_name="service_zones")
    op.drop_column("service_zones", "deleted_at")
