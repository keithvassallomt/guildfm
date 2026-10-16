"""Jingles: GuildFM's station idents and each station's show idents.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-16 23:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jingles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("station", "show", name="jinglekind", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("station_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("file", sa.String(length=64), nullable=False),
        sa.Column("seconds", sa.Double(), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("stations", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("jingles", sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table("stations", schema=None) as batch_op:
        batch_op.drop_column("jingles")
    op.drop_table("jingles")
