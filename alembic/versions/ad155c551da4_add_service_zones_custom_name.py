"""add service_zones custom_name

Revision ID: ad155c551da4
Revises: cd787da37d47
Create Date: 2026-06-11 14:04:20.308681

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad155c551da4'
down_revision: Union[str, Sequence[str], None] = 'cd787da37d47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "service_zones",
        sa.Column("custom_name", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("service_zones", "custom_name")
