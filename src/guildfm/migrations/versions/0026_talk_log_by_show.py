"""A talk station's log is kept by show: each show's running bits, what it talked about and the
DJs' hooks it had, so later shows don't repeat its topics or lean on the same hooks. The running
bits logged so far become shows, one a day, with nothing known of their topics or hooks.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-20 12:00:00.000000
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rewrite(change) -> None:
    db = op.get_bind()
    for station_id, log in db.execute(sa.text("SELECT id, talk_log FROM stations")).all():
        entries = json.loads(log) if isinstance(log, str) else log
        db.execute(
            sa.text("UPDATE stations SET talk_log = :log WHERE id = :id"),
            {"log": json.dumps(change(entries or [])), "id": station_id},
        )


def _by_show(bits: list[dict]) -> list[dict]:
    shows: list[dict] = []
    for bit in bits:
        if not shows or shows[-1]["on"] != bit["on"]:
            shows.append({"on": bit["on"], "bits": [], "topics": [], "hooks": {}})
        shows[-1]["bits"].append({"move": bit["move"], "idea": bit["idea"]})
    return shows


def _by_bit(shows: list[dict]) -> list[dict]:
    return [{"on": show["on"], **bit} for show in shows for bit in show["bits"]]


def upgrade() -> None:
    _rewrite(_by_show)


def downgrade() -> None:
    _rewrite(_by_bit)
