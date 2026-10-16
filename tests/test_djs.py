import sqlite3

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from guildfm.config import Settings
from guildfm.db import MIGRATIONS, upgrade_to_head
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
        hosts = db.execute("SELECT name, dj_id FROM stations ORDER BY id").fetchall()
    db.close()
    assert made == [(1, "Guildbert", "Cheeky.", "cedar"), (2, "Della", "Cheeky.", "cedar")]
    # Della's station had its DJ switched off, so she's kept, but not on it.
    assert hosts == [("Lunchtime", 1), ("Teatime", 1), ("Quiet", None), ("Plain", None)]
