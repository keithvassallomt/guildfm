"""Jingles renamed: GuildFM's own idents are system idents, and a station's own are station
idents (they were station and show idents).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-17 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE jingles SET kind = CASE kind WHEN 'station' THEN 'system' "
        "WHEN 'show' THEN 'station' ELSE kind END"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE jingles SET kind = CASE kind WHEN 'station' THEN 'show' "
        "WHEN 'system' THEN 'station' ELSE kind END"
    )
