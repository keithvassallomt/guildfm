"""Each person's newest "What's new" seen. Everyone here already has seen up to 0.1.2, the
version before there was any, so they're shown what's new from the next one on.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-06 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("news_seen", sa.String(length=20), nullable=False, server_default="0.1.2")
        )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("news_seen")
