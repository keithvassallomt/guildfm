"""DJs of their own, so one DJ can host several stations. Each station's DJ becomes a DJ, the
same name, personality and voice becoming one.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-17 10:30:00.000000
"""

import time
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "djs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("personality", sa.String(length=600), nullable=False),
        sa.Column("voice", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("stations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("dj_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_stations_dj_id_djs", "djs", ["dj_id"], ["id"], ondelete="SET NULL"
        )

    # A station with its DJ switched off keeps the DJ it had as a DJ, for reuse, unattached.
    db = op.get_bind()
    made: dict[tuple[str, str, str], int] = {}
    rows = db.execute(
        sa.text("SELECT id, dj, dj_name, personality, voice FROM stations WHERE dj_name != ''")
    )
    for station_id, on, name, personality, voice in rows.all():
        key = (name, personality, voice)
        if key not in made:
            db.execute(
                sa.text(
                    "INSERT INTO djs (name, personality, voice, created_at) "
                    "VALUES (:name, :personality, :voice, :now)"
                ),
                {"name": name, "personality": personality, "voice": voice, "now": time.time()},
            )
            made[key] = db.execute(sa.text("SELECT last_insert_rowid()")).scalar_one()
        if on:
            db.execute(
                sa.text("UPDATE stations SET dj_id = :dj WHERE id = :id"),
                {"dj": made[key], "id": station_id},
            )

    with op.batch_alter_table("stations", schema=None) as batch_op:
        batch_op.drop_column("dj")
        batch_op.drop_column("dj_name")
        batch_op.drop_column("personality")
        batch_op.drop_column("voice")


def downgrade() -> None:
    with op.batch_alter_table("stations", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("dj", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("dj_name", sa.String(length=40), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("personality", sa.String(length=600), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("voice", sa.String(length=64), nullable=False, server_default="marin")
        )
    op.execute(
        "UPDATE stations SET dj = 1, "
        "dj_name = (SELECT name FROM djs WHERE djs.id = stations.dj_id), "
        "personality = (SELECT personality FROM djs WHERE djs.id = stations.dj_id), "
        "voice = (SELECT voice FROM djs WHERE djs.id = stations.dj_id) "
        "WHERE dj_id IS NOT NULL"
    )
    with op.batch_alter_table("stations", schema=None) as batch_op:
        batch_op.drop_constraint("fk_stations_dj_id_djs", type_="foreignkey")
        batch_op.drop_column("dj_id")
    op.drop_table("djs")
