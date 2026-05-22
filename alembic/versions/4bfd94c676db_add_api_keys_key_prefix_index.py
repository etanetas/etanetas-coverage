"""add api_keys.key_prefix + index

Revision ID: 4bfd94c676db
Revises: 0001
Create Date: 2026-05-22 11:29:00.202109

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4bfd94c676db'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "api_keys",
        sa.Column("key_prefix", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "ix_api_keys_key_prefix",
        "api_keys",
        ["key_prefix"],
        unique=False,
    )
    # NOTE: ix_api_keys_active (partial index on user_id WHERE revoked_at IS NULL)
    # is already present as idx_api_keys_user defined in the model __table_args__
    # and created in migration 0001. Skipping duplicate creation.


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_api_keys_key_prefix", table_name="api_keys")
    op.drop_column("api_keys", "key_prefix")
