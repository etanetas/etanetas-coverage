"""add_locality_name_k

Revision ID: b4bb0915d15b
Revises: 59bce5ed616f
Create Date: 2026-05-20 08:51:18.254988

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4bb0915d15b'
down_revision: Union[str, Sequence[str], None] = '59bce5ed616f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("localities", sa.Column("name_k", sa.Text(), nullable=True))
    op.create_index(
        "idx_localities_name_k_trgm",
        "localities",
        ["name_k"],
        postgresql_using="gin",
        postgresql_ops={"name_k": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("idx_localities_name_k_trgm", table_name="localities")
    op.drop_column("localities", "name_k")
