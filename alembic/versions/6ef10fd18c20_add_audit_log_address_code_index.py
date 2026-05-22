"""add audit_log.address_code + index

Revision ID: 6ef10fd18c20
Revises: 4bfd94c676db
Create Date: 2026-05-22 11:34:37.279654

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6ef10fd18c20'
down_revision: Union[str, Sequence[str], None] = '4bfd94c676db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("audit_log", sa.Column("address_code", sa.BigInteger(), nullable=True))
    op.create_index(
        "ix_audit_log_address_code",
        "audit_log",
        ["address_code"],
        postgresql_where=sa.text("address_code IS NOT NULL"),
    )
    # Backfill from existing diff JSON — only match numeric values
    op.execute("""
        UPDATE audit_log
        SET address_code = (diff->>'address_code')::bigint
        WHERE entity_type = 'address_offering'
          AND (diff->>'address_code') ~ '^[0-9]+$'
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_audit_log_address_code", table_name="audit_log")
    op.drop_column("audit_log", "address_code")
