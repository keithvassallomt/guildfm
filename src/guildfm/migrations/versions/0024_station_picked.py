"""Stations stop keeping their last 150 picks: a station now rests every song heard in the
office for a week, from the play history, and plays songs from before from it too.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-15 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("stations", schema=None) as batch_op:
        batch_op.drop_column("picked")


def downgrade() -> None:
    with op.batch_alter_table("stations", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("picked", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )
