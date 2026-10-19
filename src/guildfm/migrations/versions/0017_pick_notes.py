"""Why the AI picked each song and the jingle it wants before it, kept in the database so they
survive a restart.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-19 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pick_notes",
        sa.Column("track_id", sa.String(length=32), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.Column("ident", sa.String(length=16), nullable=True),
        sa.Column("picked_at", sa.Double(), nullable=False),
        sa.ForeignKeyConstraint(["track_id"], ["tracks.id"]),
        sa.PrimaryKeyConstraint("track_id"),
    )
    op.create_index("ix_pick_notes_picked_at", "pick_notes", ["picked_at"])


def downgrade() -> None:
    op.drop_index("ix_pick_notes_picked_at", table_name="pick_notes")
    op.drop_table("pick_notes")
