"""Where each play came from, and where a playlist left off.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-16 14:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("plays", schema=None) as batch_op:
        batch_op.add_column(sa.Column("playlist_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_plays_playlist_id", ["playlist_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_plays_playlist_id_playlists",
            "playlists",
            ["playlist_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("playlists", schema=None) as batch_op:
        batch_op.add_column(sa.Column("resume", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("playlists", schema=None) as batch_op:
        batch_op.drop_column("resume")
    with op.batch_alter_table("plays", schema=None) as batch_op:
        batch_op.drop_constraint("fk_plays_playlist_id_playlists", type_="foreignkey")
        batch_op.drop_index("ix_plays_playlist_id")
        batch_op.drop_column("playlist_id")
