"""add_audit_log_entity_time_index

Revision ID: 9757d93296ad
Revises: 23d4663af70b
Create Date: 2026-05-20 14:15:13.613600

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9757d93296ad'
down_revision: Union[str, Sequence[str], None] = '23d4663af70b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_audit_log_entity_time",
        "audit_log",
        ["entity_type", "entity_id", "at"],
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_index("idx_audit_log_entity_time", table_name="audit_log")
