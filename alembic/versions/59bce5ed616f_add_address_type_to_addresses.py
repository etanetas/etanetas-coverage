"""add_address_type_to_addresses

Revision ID: 59bce5ed616f
Revises: 2b10a2f6d3a1
Create Date: 2026-05-20 08:33:10.898748

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '59bce5ed616f'
down_revision: Union[str, Sequence[str], None] = '2b10a2f6d3a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "addresses",
        sa.Column(
            "address_type",
            sa.Text(),
            nullable=False,
            server_default="building",
        ),
    )
    op.create_index("idx_addresses_type", "addresses", ["address_type"])


def downgrade() -> None:
    op.drop_index("idx_addresses_type", table_name="addresses")
    op.drop_column("addresses", "address_type")
