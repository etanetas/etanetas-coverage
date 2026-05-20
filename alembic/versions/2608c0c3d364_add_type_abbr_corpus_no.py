"""add_type_abbr_corpus_no

Revision ID: 2608c0c3d364
Revises: b4bb0915d15b
Create Date: 2026-05-20 09:00:22.707407

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2608c0c3d364'
down_revision: Union[str, Sequence[str], None] = 'b4bb0915d15b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("streets", sa.Column("type_abbr", sa.Text(), nullable=True))
    op.add_column("localities", sa.Column("type_abbr", sa.Text(), nullable=True))
    op.add_column("addresses", sa.Column("corpus_no", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("addresses", "corpus_no")
    op.drop_column("localities", "type_abbr")
    op.drop_column("streets", "type_abbr")
