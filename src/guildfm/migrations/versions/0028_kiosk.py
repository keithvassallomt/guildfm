"""The kiosk: a role for the touchscreen in the office, its places and breaks, and its votes,
which count up to two each way on a song and are kept apart from people's.

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-27 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("kiosk_since", sa.Float(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(sa.Column("kiosk_break_until", sa.Float(), nullable=True))
    op.create_table(
        "kiosk_votes",
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("up", sa.Integer(), nullable=False),
        sa.Column("down", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["entry_id"], ["queue.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("entry_id", "user_id"),
    )


def downgrade() -> None:
    op.drop_table("kiosk_votes")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("kiosk_break_until")
        batch_op.drop_column("kiosk_since")
