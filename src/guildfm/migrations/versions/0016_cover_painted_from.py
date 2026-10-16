"""What each station's cover was painted from, so saving the name and description a cover was
just painted from doesn't paint another.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-17 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("stations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("art_for", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("stations", schema=None) as batch_op:
        batch_op.drop_column("art_for")
