import sqlite3

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from guildfm.config import Settings
from guildfm.db import MIGRATIONS, upgrade_to_head
from guildfm.models import DJProfile, Station, StationDJ
from tests.helpers import ADMIN, sign_in

GUILDBERT = {"dj": True, "dj_name": "Guildbert", "personality": "Cheeky.", "voice": "cedar"}


def make_station(client: TestClient, name: str, **fields) -> dict:
    body = {"name": name, "description": "Upbeat soul for the lunch hour.", **fields}
    response = client.post("/api/stations", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def edit(client: TestClient, station: dict, **fields):
    body = {"name": station["name"], "description": station["description"], **fields}
    return client.put(f"/api/stations/{station['id']}", json=body)


def djs(client: TestClient) -> list[dict]:
    return client.get("/api/djs").json()


def test_a_dj_can_host_more_than_one_station(client: TestClient, people) -> None:
    sign_in(client, *people["curator"])
    lunch = make_station(client, "Lunchtime", **GUILDBERT)
    (guildbert,) = djs(client)
    assert (guildbert["name"], guildbert["voice"]) == ("Guildbert", "cedar")
    assert [s["name"] for s in guildbert["stations"]] == ["Lunchtime"]
    assert lunch["dj_id"] == guildbert["id"]

    tea = make_station(client, "Teatime", **GUILDBERT, dj_id=guildbert["id"])
    assert [s["name"] for s in djs(client)[0]["stations"]] == ["Lunchtime", "Teatime"]

    # Changing him on one station changes him on both. How often he talks doesn't.
    changed = GUILDBERT | {"personality": "Very cheeky.", "voice": "marin", "talk_every": 5}
    edit(client, tea, **changed, dj_id=guildbert["id"]).raise_for_status()
    lunch = client.get(f"/api/stations/{lunch['id']}").json()
    assert (lunch["personality"], lunch["voice"], lunch["talk_every"]) == (
        "Very cheeky.",
        "marin",
        3,
    )
    assert len(djs(client)) == 1


def test_each_dj_has_their_own_name(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    make_station(client, "Lunchtime", **GUILDBERT)
    clash = client.post(
        "/api/stations",
        json={"name": "Teatime", "description": "Soul.", **GUILDBERT, "dj_name": "guildbert"},
    )
    assert clash.status_code == 409
    assert "already a DJ called guildbert" in clash.json()["detail"]
    della = make_station(client, "Teatime", dj=True, dj_name="Della")
    renamed = edit(client, della, dj=True, dj_id=della["dj_id"], dj_name="Guildbert")
    assert renamed.status_code == 409
    gone = edit(client, della, dj=True, dj_id=999, dj_name="Somebody")
    assert gone.status_code == 404


def test_a_dj_stays_when_no_station_has_them(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    lunch = make_station(client, "Lunchtime", **GUILDBERT)
    quiet = edit(client, lunch, dj=False).json()
    assert (quiet["dj"], quiet["dj_id"], quiet["dj_name"]) == (False, None, "")
    client.delete(f"/api/stations/{lunch['id']}").raise_for_status()
    assert [(dj["name"], dj["stations"]) for dj in djs(client)] == [("Guildbert", [])]


def test_only_station_makers_see_the_djs(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    assert client.get("/api/djs").status_code == 403


def test_stations_djs_become_djs(settings: Settings) -> None:
    """The migration: each station's DJ becomes a DJ, the same one becoming one."""
    settings.data_dir.mkdir(parents=True)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", settings.sync_database_url)
    command.upgrade(config, "0014")
    columns = (
        "name, kind, description, global_awareness, dj, dj_name, personality, voice, "
        "talk_every, talk_unit, style, announce_requests, created_at, picked"
    )
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        for name, dj, dj_name in [
            ("Lunchtime", 1, "Guildbert"),
            ("Teatime", 1, "Guildbert"),
            ("Quiet", 0, "Della"),
            ("Plain", 0, ""),
        ]:
            db.execute(
                f"INSERT INTO stations ({columns}) VALUES "
                "(?, 'custom', 'Soul.', 0, ?, ?, 'Cheeky.', 'cedar', 3, 'tracks', 'commentary', "
                "1, 0, '[]')",
                (name, dj, dj_name),
            )
    db.close()

    upgrade_to_head(settings.sync_database_url)
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        made = db.execute("SELECT id, name, personality, voice FROM djs ORDER BY id").fetchall()
        hosts = db.execute(
            "SELECT name, dj_id FROM stations LEFT JOIN station_djs ON station_id = stations.id "
            "ORDER BY stations.id"
        ).fetchall()
    db.close()
    assert made == [(1, "Guildbert", "Cheeky.", "cedar"), (2, "Della", "Cheeky.", "cedar")]
    # Della's station had its DJ switched off, so she's kept, but not on it.
    assert hosts == [("Lunchtime", 1), ("Teatime", 1), ("Quiet", None), ("Plain", None)]


def _config(settings: Settings) -> Config:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", settings.sync_database_url)
    return config


STATION_0024 = (
    "INSERT INTO stations (name, kind, description, global_awareness, dj_id, talk_every, "
    "talk_unit, style, announce_requests, jingles, crossfade, created_at, ready) VALUES "
    "(?, 'custom', 'Soul.', 0, ?, 3, 'tracks', 'commentary', 1, 1, 0, 0, '[]')"
)


def test_a_stations_dj_becomes_its_first_dj(settings: Settings) -> None:
    """The talk stations migration: a station's DJ is its first DJ, DJs start with no hooks,
    and no station is a talk station."""
    config = _config(settings)
    command.upgrade(config, "0024")
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        db.execute(
            "INSERT INTO djs (name, personality, voice, created_at) "
            "VALUES ('Guildbert', 'Cheeky.', 'cedar', 0)"
        )
        db.execute(STATION_0024, ("Lunchtime", 1))
        db.execute(STATION_0024, ("Plain", None))
    db.close()

    upgrade_to_head(settings.sync_database_url)
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        hosting = db.execute("SELECT station_id, dj_id, position FROM station_djs").fetchall()
        hooks = db.execute("SELECT pet_peeves, soft_spots, obsession FROM djs").fetchall()
        talk = db.execute(
            "SELECT dynamic, talk_station, talk_ratio, script_prompt FROM stations"
        ).fetchall()
    db.close()
    assert hosting == [(1, 1, 0)]
    assert hooks == [("", "", "")]
    assert talk == [("", 0, 40, ""), ("", 0, 40, "")]


def test_going_back_keeps_a_stations_first_dj(settings: Settings) -> None:
    config = _config(settings)
    upgrade_to_head(settings.sync_database_url)
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        for name in ("Guildbert", "Debbie"):
            db.execute(
                "INSERT INTO djs (name, personality, voice, created_at) VALUES (?, '', 'cedar', 0)",
                (name,),
            )
        db.execute(
            "INSERT INTO stations (name, kind, description, global_awareness, talk_every, "
            "talk_unit, style, announce_requests, jingles, crossfade, created_at, ready) VALUES "
            "('Lunch Break', 'custom', 'Soul.', 0, 3, 'tracks', 'commentary', 1, 1, 0, 0, '[]')"
        )
        # Debbie first.
        db.execute("INSERT INTO station_djs VALUES (1, 1, 1), (1, 2, 0)")
    db.close()

    command.downgrade(config, "0024")
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        assert db.execute("SELECT dj_id FROM stations").fetchall() == [(2,)]
    db.close()


async def _host_too(sessionmaker, station_id: int, name: str, first: bool) -> None:
    """Puts a new DJ on the station, first or last."""
    async with sessionmaker() as db:
        station = await db.get(Station, station_id)
        dj = DJProfile(
            name=name,
            personality="Bubbly.",
            voice="elevenlabs:abc",
            pet_peeves="Long stories.",
            created_at=0.0,
        )
        db.add(dj)
        station.set_hosts([dj, *station.hosts] if first else [*station.hosts, dj])
        await db.commit()


async def _reverse(sessionmaker, station_id: int) -> None:
    async with sessionmaker() as db:
        station = await db.get(Station, station_id)
        station.set_hosts(list(reversed(station.hosts)))
        await db.commit()


async def _hosting(sessionmaker) -> list[tuple]:
    async with sessionmaker() as db:
        rows = await db.execute(
            select(StationDJ.station_id, DJProfile.name, StationDJ.position, DJProfile.pet_peeves)
            .join(DJProfile, DJProfile.id == StationDJ.dj_id)
            .order_by(StationDJ.station_id, StationDJ.position)
        )
        return [tuple(row) for row in rows]


def test_a_station_keeps_its_djs_in_order(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    lunch = make_station(client, "Lunch Break", **GUILDBERT)
    sessions = client.app.state.sessionmaker

    client.portal.call(_host_too, sessions, lunch["id"], "Debbie", False)
    assert client.portal.call(_hosting, sessions) == [
        (lunch["id"], "Guildbert", 0, ""),
        (lunch["id"], "Debbie", 1, "Long stories."),
    ]
    # Guildbert, first, still talks between songs, and both say they host it.
    assert client.get(f"/api/stations/{lunch['id']}").json()["dj_name"] == "Guildbert"
    assert {dj["name"]: [s["name"] for s in dj["stations"]] for dj in djs(client)} == {
        "Debbie": ["Lunch Break"],
        "Guildbert": ["Lunch Break"],
    }

    client.portal.call(_reverse, sessions, lunch["id"])
    assert [row[1:3] for row in client.portal.call(_hosting, sessions)] == [
        ("Debbie", 0),
        ("Guildbert", 1),
    ]
    assert client.get(f"/api/stations/{lunch['id']}").json()["dj_name"] == "Debbie"

    # The DJs outlive the station.
    client.delete(f"/api/stations/{lunch['id']}").raise_for_status()
    assert client.portal.call(_hosting, sessions) == []
    assert [(dj["name"], dj["stations"]) for dj in djs(client)] == [
        ("Debbie", []),
        ("Guildbert", []),
    ]
