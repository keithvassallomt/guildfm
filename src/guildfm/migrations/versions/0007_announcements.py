"""Announcements, and the log of what played.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-16 16:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=600), nullable=False),
        sa.Column("rooms", sa.JSON(), nullable=True),
        sa.Column(
            "mode",
            sa.Enum("over", "after", name="announcemode", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("at", sa.String(length=5), nullable=False),
        sa.Column(
            "repeat",
            sa.Enum(
                "once",
                "daily",
                "weekdays",
                "days",
                "hourly",
                name="repeat",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("days", sa.JSON(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("handled_until", sa.Double(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "announcement_plays",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=600), nullable=False),
        sa.Column("rooms", sa.JSON(), nullable=True),
        sa.Column("played_at", sa.Double(), nullable=False),
        sa.Column("problem", sa.String(length=300), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("announcement_plays", schema=None) as batch_op:
        batch_op.create_index("ix_announcement_plays_played_at", ["played_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("announcement_plays", schema=None) as batch_op:
        batch_op.drop_index("ix_announcement_plays_played_at")
    op.drop_table("announcement_plays")
    op.drop_table("announcements")
