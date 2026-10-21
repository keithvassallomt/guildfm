"""The jingle generator: what a made jingle came from, drafts waiting to be kept or turned down,
and the turned down ones' descriptions.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-21 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jingles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("prompt", sa.String(length=1000), nullable=True))
        batch_op.add_column(
            sa.Column("instrumental", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.create_table(
        "jingle_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("prompt", sa.String(length=1000), nullable=False),
        sa.Column("length", sa.Integer(), nullable=False),
        sa.Column("instrumental", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "making",
                "ready",
                "failed",
                "kept",
                "turned_down",
                name="draftstatus",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("file", sa.String(length=64), nullable=True),
        sa.Column("seconds", sa.Double(), nullable=True),
        sa.Column("problem", sa.String(length=300), nullable=True),
        sa.Column("suggestion", sa.String(length=1000), nullable=True),
        sa.Column("jingle_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["jingle_id"], ["jingles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "turned_down_jingles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=True),
        sa.Column("prompt", sa.String(length=1000), nullable=False),
        sa.Column("turned_down_at", sa.Double(), nullable=False),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("turned_down_jingles")
    op.drop_table("jingle_drafts")
    with op.batch_alter_table("jingles", schema=None) as batch_op:
        batch_op.drop_column("instrumental")
        batch_op.drop_column("prompt")
