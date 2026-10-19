"""Line-ups: plans for the day, each a run of slots putting an AI station or a playlist on by the
clock. The source notes the line-up that's on.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-19 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lineups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=600), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("last_on_at", sa.Double(), nullable=True),
        sa.Column("art", sa.String(length=64), nullable=True),
        sa.Column("art_for", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "lineup_slots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lineup_id", sa.Integer(), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=True),
        sa.Column("playlist_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["lineup_id"], ["lineups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["playlist_id"], ["playlists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lineup_slots_lineup_id", "lineup_slots", ["lineup_id"])
    with op.batch_alter_table("playback_source", schema=None) as batch_op:
        batch_op.add_column(sa.Column("lineup_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_playback_source_lineup_id_lineups",
            "lineups",
            ["lineup_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("playback_source", schema=None) as batch_op:
        batch_op.drop_constraint("fk_playback_source_lineup_id_lineups", type_="foreignkey")
        batch_op.drop_column("lineup_id")
    op.drop_index("ix_lineup_slots_lineup_id", table_name="lineup_slots")
    op.drop_table("lineup_slots")
    op.drop_table("lineups")
