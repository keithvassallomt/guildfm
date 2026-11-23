"""Fresh hooks: a talk show DJ's hooks rewritten by the AI one at a time, about monthly."""

import json
import sqlite3
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from guildfm.db import MIGRATIONS, upgrade_to_head
from guildfm.hooks import DAY, FreshHooks, changed_hooks, due, freshen, next_fresh
from guildfm.models import DJProfile, Station
from guildfm.prefs import DEFAULTS
from tests.fakes import FakeOpenAI

ZONE = ZoneInfo(DEFAULTS["timezone"])
NOW = datetime(2026, 11, 23, 14, 0, tzinfo=ZONE).timestamp()  # a Monday afternoon


def dj(**changes) -> DJProfile:
    fields = {
        "name": "Debbie",
        "personality": "Bubbly.",
        "voice": "elevenlabs:aurora02",
        "pet_peeves": "Fish in the office microwave.",
        "soft_spots": "Power ballads.",
        "obsession": "Her allotment.",
        "hooks_at": {"pet_peeves": NOW - 20 * DAY, "soft_spots": NOW - 10 * DAY, "obsession": NOW},
        "old_hooks": [],
        "fresh_hooks": True,
        "created_at": 0,
    }
    return DJProfile(**(fields | changes))


def test_a_blank_hook_is_filled_first_then_the_oldest_once_its_a_month_old() -> None:
    assert due(dj(obsession=""), NOW) == "obsession"
    assert due(dj(), NOW) is None
    assert due(dj(), NOW + 10 * DAY) == "pet_peeves"
    assert due(dj(hooks_at={}), NOW) == "pet_peeves"  # with no age, as old as can be


def test_the_next_hook_is_new_by_the_morning_after_its_due() -> None:
    # Due now, in the afternoon: tonight, so by tomorrow morning.
    assert next_fresh(dj(obsession=""), NOW, ZONE) == ("obsession", date(2026, 11, 24))
    # Due now, in the night: by this morning.
    night = datetime(2026, 11, 23, 3, 0, tzinfo=ZONE).timestamp()
    assert next_fresh(dj(obsession=""), night, ZONE) == ("obsession", date(2026, 11, 23))
    # Her pet peeves are 30 days old on 3 December at 14:00, and new by the next morning.
    assert next_fresh(dj(), NOW, ZONE) == ("pet_peeves", date(2026, 12, 4))


def test_a_hook_changed_by_hand_starts_its_month_again_and_the_old_one_is_kept() -> None:
    later = NOW + DAY
    hooks = {"pet_peeves": "Lukewarm tea.", "soft_spots": "Power ballads.", "obsession": ""}
    at, old = changed_hooks(dj(), hooks, later)
    assert at == {"pet_peeves": later, "soft_spots": NOW - 10 * DAY}
    assert old == ["Fish in the office microwave.", "Her allotment."]


async def _djs(sessionmaker) -> None:
    async with sessionmaker() as db:
        talk = Station(name="The Lunch Break", description="Soul.", talk_station=True, created_at=0)
        music = Station(name="Easy Does It", description="Easy.", created_at=0)
        debbie = dj(obsession="", old_hooks=["Finding out who nicks her yoghurts."])
        guildbert = dj(name="Guildbert", obsession="", fresh_hooks=False)
        della = dj(name="Della", obsession="")  # hosts no talk show
        talk.set_hosts([debbie, guildbert])
        music.set_hosts([della])
        db.add_all([talk, music])
        await db.commit()


async def _dj(sessionmaker, name: str) -> DJProfile:
    async with sessionmaker() as db:
        return await db.scalar(select(DJProfile).where(DJProfile.name == name))


def test_a_talk_show_dj_with_a_hook_due_gets_it_rewritten(
    client: TestClient, openai: FakeOpenAI
) -> None:
    sessionmaker, ai = client.app.state.sessionmaker, client.app.state.ai
    client.portal.call(_djs, sessionmaker)
    changed = client.portal.call(freshen, sessionmaker, ai, NOW)
    assert changed == ["Debbie's new running obsession: Pigeons on the office window ledge."]
    (asked,) = openai.asked_for("dj_hook")
    assert "- Finding out who nicks her yoghurts." in asked["input"]  # not to come back
    assert "Pet peeves: Fish in the office microwave." in asked["input"]  # staying
    assert "Write Debbie's new running obsession" in asked["input"]
    debbie = client.portal.call(_dj, sessionmaker, "Debbie")
    assert debbie.obsession == "Pigeons on the office window ledge."
    assert debbie.hooks_at["obsession"] == NOW
    # Guildbert has fresh hooks off, and Della hosts no talk show.
    assert client.portal.call(_dj, sessionmaker, "Guildbert").obsession == ""
    assert client.portal.call(_dj, sessionmaker, "Della").obsession == ""
    # Nothing else is due the next night.
    assert client.portal.call(freshen, sessionmaker, ai, NOW + DAY) == []


def test_hooks_are_rewritten_once_a_night(client: TestClient, openai: FakeOpenAI) -> None:
    sessionmaker = client.app.state.sessionmaker
    client.portal.call(_djs, sessionmaker)
    fresh = FreshHooks(sessionmaker, client.app.state.ai)
    client.portal.call(fresh.tick, NOW)  # the afternoon
    assert openai.asked_for("dj_hook") == []
    night = datetime(2026, 11, 24, 2, 0, tzinfo=ZONE).timestamp()
    client.portal.call(fresh.tick, night)
    client.portal.call(fresh.tick, night + 3600)
    assert len(openai.asked_for("dj_hook")) == 1


def test_existing_hooks_are_spread_out_so_they_dont_all_change_at_once(settings) -> None:
    """The migration: each hook a DJ has gets an age, a blank one none, so it's filled first."""
    settings.data_dir.mkdir(parents=True)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", settings.sync_database_url)
    command.upgrade(config, "0026")
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        db.execute(
            "INSERT INTO djs (name, personality, voice, pet_peeves, soft_spots, obsession, "
            "created_at) VALUES ('Debbie', 'Bubbly.', 'elevenlabs:aurora02', 'Fish.', "
            "'Power ballads.', '', 0)"
        )
    db.close()
    before = time.time()
    upgrade_to_head(settings.sync_database_url)
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        fresh, at, old = db.execute("SELECT fresh_hooks, hooks_at, old_hooks FROM djs").fetchone()
    db.close()
    ages = {hook: before - when for hook, when in json.loads(at).items()}
    assert set(ages) == {"pet_peeves", "soft_spots"}  # her blank obsession is filled first
    assert 19.9 * DAY < ages["pet_peeves"] < 20 * DAY
    assert 9.9 * DAY < ages["soft_spots"] < 10 * DAY
    assert (fresh, json.loads(old)) == (1, [])
