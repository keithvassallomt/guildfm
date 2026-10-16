"""Whole albums in the queue, for curators and admins.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-17 00:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("queue", schema=None) as batch_op:
        batch_op.add_column(sa.Column("album_id", sa.String(length=22), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("queue", schema=None) as batch_op:
        batch_op.drop_column("album_id")
