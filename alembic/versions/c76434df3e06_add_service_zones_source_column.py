"""add service_zones source column

Revision ID: c76434df3e06
Revises: 75bf647fc397
Create Date: 2026-06-11 08:55:10.593502

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c76434df3e06'
down_revision: str | Sequence[str] | None = '75bf647fc397'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "service_zones",
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
    )
    op.create_check_constraint(
        "ck_service_zones_source", "service_zones", "source IN ('manual', 'auto')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_service_zones_source", "service_zones", type_="check")
    op.drop_column("service_zones", "source")
