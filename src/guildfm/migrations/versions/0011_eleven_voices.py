"""Room in a station's voice for an ElevenLabs voice's id.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-16 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("stations", schema=None) as batch_op:
        batch_op.alter_column(
            "voice", existing_type=sa.String(length=16), type_=sa.String(length=64)
        )


def downgrade() -> None:
    with op.batch_alter_table("stations", schema=None) as batch_op:
        batch_op.alter_column(
            "voice", existing_type=sa.String(length=64), type_=sa.String(length=16)
        )
