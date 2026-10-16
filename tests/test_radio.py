import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from guildfm.config import Settings
from guildfm.radio import same_artist
from tests.fakes import FakeOpenAI, FakeSpeakers, FakeWeather, spotify_id
from tests.helpers import ADMIN, read_speakers, sign_in

FLEETWOOD = [
    {"title": f"Song {n}", "artist": "Fleetwood Mac", "note": f"Note {n}"} for n in range(1, 13)
]


def make_station(client: TestClient, **fields) -> dict:
    body = {"name": "Lunchtime Grooves", "description": "Upbeat soul for the lunch hour.", **fields}
    response = client.post("/api/stations", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def put_on(client: TestClient, station: dict) -> None:
    """Put the station on and wait for its first songs to be picked."""
    client.post(f"/api/stations/{station['id']}/play").raise_for_status()
    client.portal.call(client.app.state.radio.settle)


def queue(client: TestClient) -> dict:
    return client.get("/api/queue").json()


def upcoming(client: TestClient) -> list[str]:
    return [song["track"]["title"] for song in queue(client)["source"]["upcoming"]]


def playing(client: TestClient) -> str | None:
    entry = queue(client)["playing"]
    return entry and entry["track"]["title"]


def song_ends(client: TestClient, speakers: FakeSpeakers) -> None:
    speakers.track_position = 190
    read_speakers(client)
    speakers.song_ends()
    read_speakers(client)


def played(settings: Settings, track_id: str, title: str, artists: str) -> None:
    """Put a play in the history, as if it played this morning."""
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        db.execute(
            "INSERT OR IGNORE INTO tracks (id, title, artists, album, duration_ms, explicit) "
            "VALUES (?, ?, ?, '', 200000, 0)",
            (track_id, title, artists),
        )
        db.execute(
            "INSERT INTO plays (track_id, played_at, upvotes, downvotes) VALUES (?, ?, 0, 0)",
            (track_id, time.time()),
        )


# Making stations


def test_curators_make_stations(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    assert client.get("/api/stations").status_code == 403
    assert client.post("/api/stations", json={"name": "x", "description": "y"}).status_code == 403

    sign_in(client, *people["curator"])
    made = make_station(client, dj=True, dj_name="Della", personality="Warm and upbeat.")
    assert (made["made_by"], made["dj_name"], made["talk_every"]) == ("Curator", "Della", 3)
    assert [s["name"] for s in client.get("/api/stations").json()] == [
        "Lunchtime Grooves",
        "AI picks",
    ]

    no_name = client.post("/api/stations", json={"name": "x", "description": "y", "dj": True})
    assert no_name.status_code == 422
    assert "Give the DJ a name." in no_name.text

    body = {"name": "Lunch", "description": "Soul.", "talk_every": 10, "talk_unit": "minutes"}
    changed = client.put(f"/api/stations/{made['id']}", json=body).json()
    assert (changed["name"], changed["talk_every"], changed["talk_unit"]) == (
        "Lunch",
        10,
        "minutes",
    )
    assert client.delete(f"/api/stations/{made['id']}").status_code == 204


def test_ai_picks_looks_after_itself(client: TestClient, people) -> None:
    sign_in(client, *people["curator"])
    picks = client.get("/api/stations").json()[0]
    assert (picks["name"], picks["kind"]) == ("AI picks", "ai_picks")
    body = {"name": "Mine", "description": "Mine."}
    assert client.put(f"/api/stations/{picks['id']}", json=body).status_code == 409
    assert client.delete(f"/api/stations/{picks['id']}").status_code == 409


def test_hearing_the_dj(client: TestClient, people, openai: FakeOpenAI) -> None:
    sign_in(client, *people["curator"])
    body = {"text": "Afternoon!", "voice": "ash", "dj_name": "Della", "personality": "Warm."}
    response = client.post("/api/stations/preview", json=body)
    assert response.headers["content-type"] == "audio/mpeg"
    spoken = openai.requests[-1]
    assert (spoken["voice"], spoken["input"]) == ("ash", "Afternoon!")
    assert "Della" in spoken["instructions"] and "Warm." in spoken["instructions"]


# Picking songs


def test_the_ai_picks_and_spotify_finds_them(client: TestClient, openai: FakeOpenAI) -> None:
    openai.picks = FLEETWOOD
    sign_in(client, *ADMIN)
    put_on(client, make_station(client))

    asked = openai.asked_for("picks")[0]
    assert "Lunchtime Grooves" in asked["instructions"]
    assert "Station brief: Upbeat soul for the lunch hour." in asked["input"]
    source = queue(client)["source"]
    assert (source["kind"], source["name"]) == ("station", "Lunchtime Grooves")
    assert upcoming(client) == ["Song 1", "Song 2", "Song 3"]
    assert client.app.state.radio.notes[spotify_id("fm1")] == "Note 1"


def test_picks_leave_out_whats_recent_queued_or_explicit(
    client: TestClient, openai: FakeOpenAI, settings: Settings
) -> None:
    openai.picks = [
        {"title": "Dreams", "artist": "Fleetwood Mac", "note": ""},  # played this morning
        {"title": "Go Your Own Way", "artist": "Fleetwood Mac", "note": ""},  # requested
        {"title": "HUMBLE.", "artist": "Kendrick Lamar", "note": ""},  # explicit
        {"title": "Song 1", "artist": "Not Fleetwood Mac At All", "note": ""},  # wrong artist
        {"title": "Not On Spotify", "artist": "Nobody", "note": ""},
        {"title": "Song 2", "artist": "Fleetwood Mac", "note": ""},
    ]
    sign_in(client, *ADMIN)
    client.patch("/api/settings", json={"allow_explicit": False}).raise_for_status()
    played(settings, spotify_id("dreams"), "Dreams", "Fleetwood Mac")
    client.post("/api/queue", json={"track_id": spotify_id("gyow")}).raise_for_status()
    put_on(client, make_station(client))

    assert upcoming(client) == ["Song 2"]
    asked = openai.asked_for("picks")[0]["input"]
    assert "Fleetwood Mac – Dreams" in asked  # shown as played lately
    assert "Don't pick explicit songs." in asked


def test_a_station_tops_itself_up(client: TestClient, openai: FakeOpenAI, speakers) -> None:
    openai.picks = FLEETWOOD[:4]
    sign_in(client, *ADMIN)
    put_on(client, make_station(client))
    client.post("/api/playback/play").raise_for_status()
    assert playing(client) == "Song 1"

    openai.picks = FLEETWOOD[4:8]
    song_ends(client, speakers)  # Song 2 taken: two left, so more are picked
    client.portal.call(client.app.state.radio.settle)
    assert upcoming(client) == ["Song 3", "Song 4", "Song 5"]
    # It remembers what it picked, and tells the AI.
    assert "Fleetwood Mac – Song 1" in openai.asked_for("picks")[1]["input"]


def test_requests_still_play_first(client: TestClient, openai: FakeOpenAI, speakers) -> None:
    openai.picks = FLEETWOOD
    sign_in(client, *ADMIN)
    put_on(client, make_station(client))
    client.post("/api/playback/play").raise_for_status()
    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()
    song_ends(client, speakers)
    assert playing(client) == "Dreams"
    song_ends(client, speakers)
    assert playing(client) == "Song 2"
    assert queue(client)["playing"]["station"] == "Lunchtime Grooves"


def test_a_song_a_request_played_isnt_played_again(client, openai, speakers) -> None:
    openai.picks = FLEETWOOD
    sign_in(client, *ADMIN)
    put_on(client, make_station(client))
    client.post("/api/playback/play").raise_for_status()
    # Song 3 is in the station's picks, but someone asks for it now.
    client.post("/api/queue", json={"track_id": spotify_id("fm3")}).raise_for_status()
    song_ends(client, speakers)
    assert playing(client) == "Song 3"
    assert upcoming(client)[:2] == ["Song 2", "Song 4"]
    song_ends(client, speakers)
    song_ends(client, speakers)
    assert playing(client) == "Song 4"


def test_thumbs_down_skip_a_station_song(client: TestClient, people, openai) -> None:
    openai.picks = FLEETWOOD
    sign_in(client, *ADMIN)
    put_on(client, make_station(client))
    for name in ("user", "curator", "admin"):
        sign_in(client, *people[name])
        body = {"track_id": spotify_id("fm1"), "down": True}
        client.post("/api/source/vote", json=body).raise_for_status()
    assert upcoming(client) == ["Song 2", "Song 3", "Song 4"]


def test_global_awareness(client: TestClient, openai: FakeOpenAI, weather: FakeWeather) -> None:
    openai.picks = FLEETWOOD
    openai.news = "- 14 Oct: A big song contest was won."
    sign_in(client, *ADMIN)
    put_on(client, make_station(client, global_awareness=True))
    asked = openai.asked_for("picks")[0]["input"]
    assert "It's Tuesday 13 October, 10:00, morning." in asked
    assert "The weather in Carlisle, Cumbria, UK right now: light rain, 9°C" in asked
    # The news takes a while to gather, so it's in from the next time.
    assert "song contest" not in asked
    client.portal.call(client.app.state.awareness.settle)
    put_on(client, make_station(client, name="Also aware", global_awareness=True))
    assert "A big song contest was won." in openai.asked_for("picks")[1]["input"]
    news = [body for body in openai.asked if body.get("tools")]
    assert len(news) == 1  # gathered once, then kept
    assert news[0]["tools"][0]["type"] == "web_search"

    # Without it, the AI just gets the brief and what's played.
    put_on(client, make_station(client, name="Plain"))
    assert "weather" not in openai.asked_for("picks")[2]["input"]


def test_when_the_ai_finds_nothing_it_tries_again_later(client, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    station = make_station(client)
    put_on(client, station)
    assert queue(client)["source"]["upcoming"] == []
    client.portal.call(client.app.state.radio.top_up)
    assert len(openai.asked_for("picks")) == 1  # not straight away


def test_same_artist() -> None:
    assert same_artist("The Jackson 5", "Jackson 5")
    assert same_artist("Earth, Wind & Fire", "Earth, Wind & Fire")
    assert same_artist("Fleetwood Mac", "Fleetwood Mac, Christine McVie")
    assert not same_artist("Fleetwood Mac", "The Corrs")


# When the queue runs out


def test_with_nothing_chosen_ai_picks_keeps_the_music_going(client, openai, speakers) -> None:
    openai.picks = FLEETWOOD
    sign_in(client, *ADMIN)
    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()
    client.post("/api/playback/play").raise_for_status()
    speakers.track_position = 190
    read_speakers(client)
    assert queue(client)["source"]["name"] == "AI picks"
    client.portal.call(client.app.state.radio.settle)
    read_speakers(client)
    speakers.song_ends()
    read_speakers(client)
    assert playing(client) == "Song 1"
    # It follows what's been playing.
    assert "Fleetwood Mac – Dreams" in openai.asked_for("picks")[0]["input"]


def test_requests_only_means_nothing_takes_over(client, openai, speakers) -> None:
    openai.picks = FLEETWOOD
    sign_in(client, *ADMIN)
    assert client.delete("/api/source").status_code == 204
    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()
    client.post("/api/playback/play").raise_for_status()
    song_ends(client, speakers)
    assert queue(client)["source"] is None
    assert client.get("/api/playback").json()["status"] == "idle"
    assert client.get("/api/now").json()["requests_only"] is True
    assert openai.asked_for("picks") == []


@pytest.mark.parametrize("default", [True, False])
def test_or_the_default_station(client, openai, speakers, default: bool) -> None:
    openai.picks = FLEETWOOD
    sign_in(client, *ADMIN)
    station = make_station(client, name="Fridays")
    changes = {"queue_runs_out": "default_station"}
    if default:
        changes["default_station"] = station["id"]
    client.patch("/api/settings", json=changes).raise_for_status()
    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()
    client.post("/api/playback/play").raise_for_status()
    speakers.track_position = 190
    read_speakers(client)
    # Without a default station, AI picks steps in.
    assert queue(client)["source"]["name"] == ("Fridays" if default else "AI picks")


def test_the_default_station_has_to_exist(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    station = make_station(client)
    settings = client.patch("/api/settings", json={"default_station": station["id"]}).json()
    assert settings["values"]["default_station"] == station["id"]
    assert settings["stations"] == [{"id": station["id"], "name": "Lunchtime Grooves"}]
    assert client.patch("/api/settings", json={"default_station": 999}).status_code == 422

    # Deleting it clears the setting.
    client.delete(f"/api/stations/{station['id']}").raise_for_status()
    assert client.get("/api/settings").json()["values"]["default_station"] is None


# Now Playing


def test_stations_on_now_playing(client: TestClient, openai: FakeOpenAI, speakers) -> None:
    openai.picks = FLEETWOOD
    sign_in(client, *ADMIN)
    station = make_station(client, dj=True, dj_name="Della")
    put_on(client, station)
    now = client.get("/api/now").json()
    tile = next(s for s in now["stations"] if s["id"] == station["id"])
    assert (tile["filling"], tile["on_air"], tile["dj_name"]) == (True, False, "Della")

    client.post("/api/playback/play").raise_for_status()
    now = client.get("/api/now").json()
    assert now["on_air"] == "radio"
    assert [s["name"] for s in now["stations"]] == ["Lunchtime Grooves", "AI picks"]
    assert now["stations"][0]["on_air"] is True
    assert client.get("/api/history").json()["plays"][0]["station"] == "Lunchtime Grooves"


# Previewing an hour

HOUR_OF_SONGS = [
    {"title": f"Song {n}", "artist": "Fleetwood Mac", "note": f"Note {n}"} for n in range(1, 22)
]


def preview(client: TestClient, **fields):
    body = {"name": "Lunchtime Grooves", "description": "Upbeat soul for the lunch hour.", **fields}
    return client.post("/api/stations/preview-hour", json=body)


def test_an_hour_of_songs_and_what_the_dj_says(client, openai: FakeOpenAI, settings) -> None:
    openai.picks = HOUR_OF_SONGS
    openai.line = {"mode": "between", "script": "Here's another."}
    sign_in(client, *ADMIN)
    station = make_station(client)
    hour = preview(client, station_id=station["id"], dj=True, dj_name="Della", talk_every=4).json()

    # Songs of 3:20 each: 18 make the hour.
    assert hour["minutes"] == 60
    slots = hour["slots"]
    assert [slot["track"]["title"] for slot in slots] == [f"Song {n}" for n in range(1, 19)]
    assert slots[0]["note"] == "Note 1"
    assert slots[4]["starts_at"] == "2026-10-13T10:13:20+01:00"
    # The DJ talks on the first song, then every 4th.
    talks = [index for index, slot in enumerate(slots) if slot["line"]]
    assert talks == [0, 4, 8, 12, 16]
    assert slots[4]["line"] == {"where": "between", "script": "Here's another."}
    second = openai.asked_for("dj_line")[1]["input"]
    assert "It's Tuesday 13 October, 10:13, morning." in second
    assert 'Just played: "Song 4" by Fleetwood Mac.' in second
    assert "Where you talked lately: between." in second
    assert "Don't repeat yourself" in second and "- Here's another." in second

    # Nothing was kept: the station has no picks, and nothing is on.
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        row = db.execute("SELECT picked FROM stations WHERE id = ?", (station["id"],)).fetchone()
    assert row == ("[]",)
    assert queue(client)["source"] is None


def test_an_hour_with_the_dj_talking_every_few_minutes(client, openai: FakeOpenAI) -> None:
    openai.picks = HOUR_OF_SONGS
    openai.line = {"mode": "over_intro", "script": "Here's one."}
    sign_in(client, *ADMIN)
    slots = preview(client, dj=True, dj_name="Della", talk_every=10, talk_unit="minutes").json()[
        "slots"
    ]
    assert [index for index, slot in enumerate(slots) if slot["line"]] == [0, 3, 6, 9, 12, 15]
    assert slots[3]["line"]["where"] == "over_intro"


def test_an_hour_without_a_dj(client, openai: FakeOpenAI, people) -> None:
    openai.picks = HOUR_OF_SONGS
    sign_in(client, *people["curator"])
    slots = preview(client).json()["slots"]
    assert len(slots) == 18
    assert not any(slot["line"] for slot in slots)
    assert openai.asked_for("dj_line") == []

    sign_in(client, *people["user"])
    assert preview(client).status_code == 403


def test_an_hour_when_the_ai_cant_help(client, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    response = preview(client)  # it suggests nothing
    assert response.status_code == 502
    assert "Try again" in response.json()["detail"]
    openai.down = True
    assert preview(client).status_code == 502
