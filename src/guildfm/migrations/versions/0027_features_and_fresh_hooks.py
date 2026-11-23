"""A talk show's own features, and fresh hooks. A station can have recurring features, each a
name and how it works. A DJ's hooks are rewritten one at a time, about monthly, unless that's
turned off: each hook's age is kept, and the hooks they've had before.

Existing hooks are spread out so they don't all change on the same night: pet peeves are taken
as 20 days old, soft spots as 10, and a running obsession as new. A blank hook is filled first.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-23 12:00:00.000000
"""

import json
import time
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DAY = 24 * 60 * 60
AGES = {"pet_peeves": 20 * DAY, "soft_spots": 10 * DAY, "obsession": 0}


def upgrade() -> None:
    with op.batch_alter_table("stations", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("features", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )
    with op.batch_alter_table("djs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("fresh_hooks", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.add_column(
            sa.Column("hooks_at", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )
        batch_op.add_column(
            sa.Column("old_hooks", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )

    db = op.get_bind()
    now = time.time()
    rows = db.execute(sa.text("SELECT id, pet_peeves, soft_spots, obsession FROM djs")).all()
    for dj_id, *hooks in rows:
        ages = {
            hook: now - age for (hook, age), text in zip(AGES.items(), hooks, strict=True) if text
        }
        db.execute(
            sa.text("UPDATE djs SET hooks_at = :at WHERE id = :id"),
            {"at": json.dumps(ages), "id": dj_id},
        )


def downgrade() -> None:
    with op.batch_alter_table("djs", schema=None) as batch_op:
        batch_op.drop_column("old_hooks")
        batch_op.drop_column("hooks_at")
        batch_op.drop_column("fresh_hooks")
    with op.batch_alter_table("stations", schema=None) as batch_op:
        batch_op.drop_column("features")
