"""Talk stations. A station can have several DJs, in order, and say how they get on; each DJ has
hooks for the banter; and a station can be a talk station, with how much of it is talk and a
script prompt. A station's DJ becomes its first DJ.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-16 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("djs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("pet_peeves", sa.String(length=300), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("soft_spots", sa.String(length=300), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("obsession", sa.String(length=200), nullable=False, server_default="")
        )

    op.create_table(
        "station_djs",
        sa.Column("station_id", sa.Integer(), nullable=False),
        sa.Column("dj_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dj_id"], ["djs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("station_id", "dj_id"),
    )
    op.execute(
        "INSERT INTO station_djs (station_id, dj_id, position) "
        "SELECT id, dj_id, 0 FROM stations WHERE dj_id IS NOT NULL"
    )

    with op.batch_alter_table("stations", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("dynamic", sa.String(length=1000), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("talk_station", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("talk_ratio", sa.Integer(), nullable=False, server_default="40")
        )
        batch_op.add_column(
            sa.Column("script_prompt", sa.String(length=4000), nullable=False, server_default="")
        )
        batch_op.drop_constraint("fk_stations_dj_id_djs", type_="foreignkey")
        batch_op.drop_column("dj_id")


def downgrade() -> None:
    # A station keeps only its first DJ.
    with op.batch_alter_table("stations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("dj_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_stations_dj_id_djs", "djs", ["dj_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.drop_column("script_prompt")
        batch_op.drop_column("talk_ratio")
        batch_op.drop_column("talk_station")
        batch_op.drop_column("dynamic")
    op.execute(
        "UPDATE stations SET dj_id = (SELECT dj_id FROM station_djs "
        "WHERE station_djs.station_id = stations.id ORDER BY position LIMIT 1)"
    )
    op.drop_table("station_djs")

    with op.batch_alter_table("djs", schema=None) as batch_op:
        batch_op.drop_column("obsession")
        batch_op.drop_column("soft_spots")
        batch_op.drop_column("pet_peeves")
