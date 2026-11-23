import sqlite3

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from guildfm.config import Settings
from guildfm.db import MIGRATIONS, upgrade_to_head
from guildfm.models import DJProfile, Station, StationDJ
from tests.fakes import FakeElevenLabs, FakeOpenAI
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


GUILDBERT_TALKS = {
    "name": "Guildbert",
    "personality": "Cheeky.",
    "voice": "elevenlabs:guildbert01",
    "pet_peeves": "Songs that fade out.",
    "soft_spots": "Brass bands.",
    "obsession": "His marrows.",
}
DEBBIE_TALKS = {"name": "Debbie", "personality": "Bubbly.", "voice": "elevenlabs:aurora02"}
TALK = {
    "talk_station": True,
    "talk_ratio": 60,
    "dynamic": "Debbie can't let Guildbert finish a story.",
    "script_prompt": "Light chat about the [news].",
}


def test_a_talk_station_has_its_djs_in_order_with_their_hooks(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    lunch = make_station(client, "Lunch Break", djs=[GUILDBERT_TALKS, DEBBIE_TALKS], **TALK)
    assert [dj["name"] for dj in lunch["djs"]] == ["Guildbert", "Debbie"]
    assert lunch["djs"][0]["obsession"] == "His marrows."
    assert (lunch["dj_name"], lunch["talk_ratio"]) == ("Guildbert", 60)
    assert lunch["dynamic"] == "Debbie can't let Guildbert finish a story."
    assert lunch["script_prompt"] == "Light chat about the [news]."
    hooks = {dj["name"]: dj["pet_peeves"] for dj in djs(client)}
    assert hooks == {"Debbie": "", "Guildbert": "Songs that fade out."}

    # Debbie first now, both by id.
    guildbert, debbie = (dict(dj) for dj in lunch["djs"])
    swapped = edit(client, lunch, djs=[debbie, guildbert], **TALK).json()
    assert [dj["name"] for dj in swapped["djs"]] == ["Debbie", "Guildbert"]
    assert len(djs(client)) == 2

    # Guildbert edited with the one-DJ form on another station keeps his hooks.
    tea = make_station(client, "Teatime", **GUILDBERT, dj_id=guildbert["id"])
    edit(client, tea, **GUILDBERT, dj_id=guildbert["id"]).raise_for_status()
    assert {dj["name"]: dj["obsession"] for dj in djs(client)}["Guildbert"] == "His marrows."


def test_a_talk_station_needs_djs_who_can_talk_over_each_other(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    body = {"name": "Lunch Break", "description": "Soul.", **TALK}

    def refused(**fields) -> str:
        response = client.post("/api/stations", json=body | fields)
        assert response.status_code == 422, response.text
        return response.json()["detail"][0]["msg"]

    assert refused(djs=[GUILDBERT_TALKS]) == "A talk station needs two or more DJs."
    della = {"name": "Della", "voice": "marin"}
    assert refused(djs=[GUILDBERT_TALKS, della]) == (
        "A talk station's DJs need ElevenLabs voices, so they can talk over each other: Della "
        "has an OpenAI one."
    )
    twin = GUILDBERT_TALKS | {"name": "guildbert"}
    assert refused(djs=[GUILDBERT_TALKS, twin]) == "Each DJ on a station needs a name of their own."
    for ratio in (10, 101):
        assert (
            client.post(
                "/api/stations",
                json=body | {"djs": [GUILDBERT_TALKS, DEBBIE_TALKS], "talk_ratio": ratio},
            ).status_code
            == 422
        )
    # Without the switch, one DJ with any voice is fine, as ever.
    make_station(client, "Quiet", djs=[della])


def test_hearing_djs_together_before_saving(
    client: TestClient, openai: FakeOpenAI, elevenlabs: FakeElevenLabs
) -> None:
    sign_in(client, *ADMIN)
    body = {
        "name": "Lunch Break",
        "djs": [GUILDBERT_TALKS, DEBBIE_TALKS],
        "dynamic": "Debbie can't let Guildbert finish a story.",
    }
    heard = client.post("/api/stations/together", json=body)
    assert heard.status_code == 200, heard.text
    assert heard.headers["content-type"] == "audio/mpeg"
    (asked,) = openai.asked_for("talk_segment")
    assert "Debbie can't let Guildbert finish a story." in asked["instructions"]
    assert "about 30 seconds" in asked["input"]
    assert [r["voice"] for r in elevenlabs.requests] == ["guildbert01", "aurora02"]
    # Nothing saved: no DJs made.
    assert djs(client) == []

    della = {"name": "Della", "voice": "marin"}
    refused = client.post("/api/stations/together", json=body | {"djs": [GUILDBERT_TALKS, della]})
    assert refused.status_code == 422
    assert "Della has an OpenAI one" in refused.json()["detail"][0]["msg"]


def test_suggesting_how_djs_get_on(client: TestClient, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    body = {
        "name": "Lunch Break",
        "djs": [GUILDBERT_TALKS, DEBBIE_TALKS],
        "script_prompt": "Light chat about the [news].",
    }
    suggested = client.post("/api/stations/dynamic", json=body)
    assert suggested.status_code == 200, suggested.text
    assert suggested.json() == {"dynamic": openai.dynamic}
    (asked,) = openai.asked_for("dynamic")
    # From who they are, hooks and all, and what the show is about.
    assert "Guildbert: Cheeky. Pet peeves: Songs that fade out." in asked["input"]
    assert "Debbie: Bubbly." in asked["input"]
    assert "Light chat about the [news]." in asked["input"]
    # Nothing saved: no DJs made.
    assert djs(client) == []

    # One DJ has nobody to get on with.
    alone = client.post("/api/stations/dynamic", json=body | {"djs": [GUILDBERT_TALKS]})
    assert alone.status_code == 422
    openai.down = True
    failed = client.post("/api/stations/dynamic", json=body)
    assert failed.status_code == 502


def test_changing_a_stations_type(client: TestClient, people) -> None:
    """The station page's Change for the type: a talk show to just music, to a station with a
    DJ, and back to a talk show. Its DJs come off it, but stay as DJs for other stations."""
    sign_in(client, *people["curator"])
    show = make_station(client, "Lunch Break", djs=[GUILDBERT_TALKS, DEBBIE_TALKS], **TALK)
    guildbert, debbie = show["djs"]

    # As the editor sends it: the whole form, with the show's settings still in it.
    off = TALK | {"talk_station": False}
    music = edit(client, show, djs=[], **off).json()
    assert (music["dj"], music["djs"], music["talk_station"]) == (False, [], False)
    # The show's own settings stay for if it's a talk show again.
    assert (music["talk_ratio"], music["dynamic"]) == (60, TALK["dynamic"])
    assert sorted(dj["name"] for dj in djs(client)) == ["Debbie", "Guildbert"]

    with_dj = edit(client, show, djs=[debbie], **off, talk_every=1).json()
    assert [dj["name"] for dj in with_dj["djs"]] == ["Debbie"]
    assert (with_dj["dj"], with_dj["dj_name"], with_dj["talk_station"]) == (True, "Debbie", False)

    again = edit(client, show, djs=[debbie, guildbert], **TALK).json()
    assert [dj["name"] for dj in again["djs"]] == ["Debbie", "Guildbert"]
    assert again["talk_station"] is True
    # Guildbert's hooks came back with him.
    assert again["djs"][1]["obsession"] == "His marrows."
    assert len(djs(client)) == 2


def test_a_talk_show_has_features_of_its_own(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    joke = {"name": "Joke of the Day", "does": "One tells a joke; the other rates it."}
    lunch = make_station(
        client, "Lunch Break", djs=[GUILDBERT_TALKS, DEBBIE_TALKS], features=[joke], **TALK
    )
    assert lunch["features"] == [joke]
    fake = {"name": "Real or Fake?", "does": "One reads a headline; the other guesses."}
    changed = edit(client, lunch, djs=lunch["djs"], features=[fake, joke], **TALK).json()
    assert changed["features"] == [fake, joke]

    def refused(features) -> str:
        response = edit(client, lunch, djs=lunch["djs"], features=features, **TALK)
        assert response.status_code == 422, response.text
        return response.json()["detail"][0]["msg"]

    assert refused([joke, joke | {"name": "joke of the day"}]) == (
        "Each feature needs a name of its own."
    )
    refused([{"name": f"Feature {n}", "does": "Something."} for n in range(9)])
    refused([{"name": "", "does": "Something."}])


def test_a_talk_show_djs_hooks_are_freshened_unless_turned_off(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    lunch = make_station(client, "Lunch Break", djs=[GUILDBERT_TALKS, DEBBIE_TALKS], **TALK)
    guildbert, debbie = lunch["djs"]
    # Debbie has no hooks, so the AI writes her pet peeves first, tonight or the night after.
    assert guildbert["fresh_hooks"] and debbie["fresh_hooks"]
    assert debbie["next_hook"]["hook"] == "pet_peeves"
    assert guildbert["next_hook"]["hook"] in ("pet_peeves", "soft_spots", "obsession")

    # His hooks changed by hand start their month again, and the old one's kept.
    guildbert = guildbert | {"obsession": "His leeks.", "fresh_hooks": False}
    changed = edit(client, lunch, djs=[guildbert, debbie], **TALK).json()
    assert changed["djs"][0]["fresh_hooks"] is False
    assert changed["djs"][0]["next_hook"] is None
    assert {dj["name"]: dj["fresh_hooks"] for dj in djs(client)} == {
        "Debbie": True,
        "Guildbert": False,
    }
    old = client.portal.call(_old_hooks, client.app.state.sessionmaker, "Guildbert")
    assert old == ["His marrows."]


async def _old_hooks(sessionmaker, name: str) -> list[str]:
    async with sessionmaker() as db:
        return (await db.scalar(select(DJProfile).where(DJProfile.name == name))).old_hooks
