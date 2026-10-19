"""What the DJ knows about the station that's on, kept with the source so a restart doesn't
lose it: songs since it last talked, when that was, and where it talked and what it said lately.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-19 09:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("playback_source", schema=None) as batch_op:
        batch_op.add_column(sa.Column("dj_memory", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("playback_source", schema=None) as batch_op:
        batch_op.drop_column("dj_memory")
