"""AI radio stations, which can fill the gaps between requests like a playlist.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-16 18:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("custom", "ai_picks", name="stationkind", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("description", sa.String(length=600), nullable=False),
        sa.Column("global_awareness", sa.Boolean(), nullable=False),
        sa.Column("dj", sa.Boolean(), nullable=False),
        sa.Column("dj_name", sa.String(length=40), nullable=False),
        sa.Column("personality", sa.String(length=600), nullable=False),
        sa.Column("voice", sa.String(length=16), nullable=False),
        sa.Column("talk_every", sa.Integer(), nullable=False),
        sa.Column(
            "talk_unit",
            sa.Enum("tracks", "minutes", name="talkunit", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column(
            "style",
            sa.Enum("announce", "commentary", name="djstyle", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("announce_requests", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("picked", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("playback_source", schema=None) as batch_op:
        batch_op.alter_column("playlist_id", existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column("station_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_playback_source_station_id_stations",
            "stations",
            ["station_id"],
            ["id"],
            ondelete="CASCADE",
        )
    with op.batch_alter_table("queue", schema=None) as batch_op:
        batch_op.add_column(sa.Column("station_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_queue_station_id_stations", "stations", ["station_id"], ["id"], ondelete="SET NULL"
        )
    with op.batch_alter_table("plays", schema=None) as batch_op:
        batch_op.add_column(sa.Column("station_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_plays_station_id", ["station_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_plays_station_id_stations", "stations", ["station_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("plays", schema=None) as batch_op:
        batch_op.drop_constraint("fk_plays_station_id_stations", type_="foreignkey")
        batch_op.drop_index("ix_plays_station_id")
        batch_op.drop_column("station_id")
    with op.batch_alter_table("queue", schema=None) as batch_op:
        batch_op.drop_constraint("fk_queue_station_id_stations", type_="foreignkey")
        batch_op.drop_column("station_id")
    with op.batch_alter_table("playback_source", schema=None) as batch_op:
        batch_op.drop_constraint("fk_playback_source_station_id_stations", type_="foreignkey")
        batch_op.drop_column("station_id")
        batch_op.alter_column("playlist_id", existing_type=sa.Integer(), nullable=False)
    op.drop_table("stations")
