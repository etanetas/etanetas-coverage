"""add_lms_username_to_users

Revision ID: f9a906019f47
Revises: 9757d93296ad
Create Date: 2026-05-20 14:49:42.146063

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9a906019f47'
down_revision: Union[str, Sequence[str], None] = '9757d93296ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("lms_username", sa.Text(), nullable=True))
    op.create_index(
        "idx_users_lms_username", "users", ["lms_username"], unique=True,
        postgresql_where=sa.text("lms_username IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_users_lms_username", table_name="users")
    op.drop_column("users", "lms_username")
