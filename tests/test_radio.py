import sqlite3
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from guildfm.config import Settings
from guildfm.radio import same_artist
from guildfm.songs import song_key, song_line
from tests.fakes import FakeOpenAI, FakeSpeakers, FakeSpotify, FakeWeather, spotify_id
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


def played(
    settings: Settings,
    track_id: str,
    title: str,
    artists: str,
    ago: float = 0,
    station_id: int | None = None,
) -> None:
    """Put a play in the history, as if it played just now, or `ago` seconds ago, by the
    station with `station_id` if given."""
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        db.execute(
            "INSERT OR IGNORE INTO tracks (id, title, artists, album, duration_ms, explicit) "
            "VALUES (?, ?, ?, '', 200000, 0)",
            (track_id, title, artists),
        )
        db.execute(
            "INSERT INTO plays (track_id, station_id, played_at, upvotes, downvotes) "
            "VALUES (?, ?, ?, 0, 0)",
            (track_id, station_id, time.time() - ago),
        )


DAYS = 24 * 60 * 60


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


def test_the_ai_picks_and_spotify_finds_them(client: TestClient, openai, settings) -> None:
    openai.picks = FLEETWOOD
    sign_in(client, *ADMIN)
    put_on(client, make_station(client))

    asked = openai.asked_for("picks")[0]
    assert "Lunchtime Grooves" in asked["instructions"]
    assert "Station brief: Upbeat soul for the lunch hour." in asked["input"]
    source = queue(client)["source"]
    assert (source["kind"], source["name"]) == ("station", "Lunchtime Grooves")
    assert upcoming(client) == ["Song 1", "Song 2", "Song 3"]
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        query = "SELECT note FROM pick_notes WHERE track_id = ?"
        assert db.execute(query, (spotify_id("fm1"),)).fetchone() == ("Note 1",)


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
    # Shown, so the AI can pick around them.
    assert "in any version:\nFleetwood Mac – Dreams" in asked
    assert "Lined up to play. Don't pick these either:\nFleetwood Mac – Go Your Own Way" in asked
    assert "Don't pick explicit songs." in asked


def test_a_station_tops_itself_up(client: TestClient, openai: FakeOpenAI, speakers) -> None:
    openai.picks_in_turn = [FLEETWOOD[:4], [], FLEETWOOD[4:]]  # 4, none more when asked again
    sign_in(client, *ADMIN)
    put_on(client, make_station(client))
    client.post("/api/playback/play").raise_for_status()
    assert playing(client) == "Song 1"

    song_ends(client, speakers)  # Song 2 taken: two left, so more are picked
    client.portal.call(client.app.state.radio.settle)
    assert upcoming(client) == ["Song 3", "Song 4", "Song 5"]
    # The AI is told what's played and what's lined up.
    asked = openai.asked_for("picks")[2]["input"]
    heard, lined_up = asked.split("Heard in the office this past week")[1].split("Lined up")
    assert "Fleetwood Mac – Song 1" in heard
    assert "Fleetwood Mac – Song 3\nFleetwood Mac – Song 4" in lined_up


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
    assert len(openai.asked_for("picks")) == 2  # asked twice, then not again straight away


def test_when_the_ai_cant_pick_the_station_plays_songs_from_before(
    client: TestClient, openai: FakeOpenAI, settings: Settings
) -> None:
    sign_in(client, *ADMIN)
    station = make_station(client)
    for name, title, ago, here in [
        ("gyow", "Go Your Own Way", 2 * DAYS, True),
        ("dreams", "Dreams", 3 * DAYS, True),
        ("chain", "The Chain", 60 * 60, True),  # an hour ago: too recent
        ("fm2", "Song 2", 4 * DAYS, True),
        ("fm2r", "Song 2 - Remastered", 30 * 60, False),  # requested, so too recent too
        ("fm1", "Song 1", 5 * DAYS, False),  # not this station's
    ]:
        station_id = station["id"] if here else None
        played(settings, spotify_id(name), title, "Fleetwood Mac", ago, station_id)

    openai.down = True
    put_on(client, station)
    # What it's played before, the longest unheard first.
    assert upcoming(client) == ["Dreams", "Go Your Own Way"]


def test_songs_found_before_arent_searched_for_again(
    client: TestClient, openai: FakeOpenAI, spotify: FakeSpotify, settings: Settings
) -> None:
    played(settings, spotify_id("dreams"), "Dreams", "Fleetwood Mac", ago=9 * DAYS)
    openai.picks = [
        {"title": "dreams", "artist": "Fleetwood Mac", "note": ""},  # known, whatever the case
        {"title": "Song 1", "artist": "Fleetwood Mac", "note": ""},
    ]
    sign_in(client, *ADMIN)
    put_on(client, make_station(client))
    assert upcoming(client) == ["Dreams", "Song 1"]
    assert spotify.searches == ['track:"Song 1" artist:"Fleetwood Mac"']


def test_while_spotify_is_paused_the_station_plays_songs_from_before(
    client: TestClient, openai: FakeOpenAI, settings: Settings
) -> None:
    openai.picks = FLEETWOOD
    client.app.state.spotify.paused_until = time.time() + 60 * 60
    sign_in(client, *ADMIN)
    station = make_station(client)
    played(settings, spotify_id("dreams"), "Dreams", "Fleetwood Mac", 3 * DAYS, station["id"])

    put_on(client, station)
    assert upcoming(client) == ["Dreams"]
    assert openai.asked_for("picks") == []  # no point asking the AI for songs it can't find
    response = preview(client)
    assert response.status_code == 503
    assert response.json()["detail"].startswith("Spotify has paused searching until ")


def test_same_artist() -> None:
    assert same_artist("The Jackson 5", "Jackson 5")
    assert same_artist("Earth, Wind & Fire", "Earth, Wind & Fire")
    assert same_artist("Fleetwood Mac", "Fleetwood Mac, Christine McVie")
    assert not same_artist("Fleetwood Mac", "The Corrs")


# Fewer repeats


def test_one_song_whatever_the_version() -> None:
    def key(title: str, artists: str = "George Michael") -> str:
        return song_key(SimpleNamespace(title=title, artists=artists))

    assert key("Faith") == key("Faith - Remastered") == key("Faith - 2011 Remaster")
    assert key("Faith") == key("Faith (Remastered)") == key("FAITH")
    fascination = key("(Keep Feeling) Fascination", "The Human League")
    assert fascination == key("(Keep Feeling) Fascination - 2003 Remaster", "Human League")
    groovejet = key("Groovejet (If This Ain't Love)", "Spiller, Sophie Ellis-Bextor")
    assert groovejet == key("Groovejet", "Spiller")
    assert key("Faith") != key("Freedom! '90")
    assert key("Faith") != key("Faith", "Limp Bizkit")
    rio = SimpleNamespace(title="Rio - 2009 Remaster", artists="Duran Duran")
    assert song_line(rio) == "Duran Duran – Rio"


def test_a_station_rests_songs_heard_this_week(
    client: TestClient, openai: FakeOpenAI, spotify: FakeSpotify, settings: Settings
) -> None:
    spotify.tracks.append(spotify.track("dreams04", "Dreams - 2004 Remaster", "Fleetwood Mac", ""))
    played(settings, spotify_id("dreams"), "Dreams", "Fleetwood Mac", ago=6 * DAYS)
    played(settings, spotify_id("fm1"), "Song 1", "Fleetwood Mac", ago=9 * DAYS)
    openai.picks = [
        {"title": "Dreams - 2004 Remaster", "artist": "Fleetwood Mac", "note": ""},
        {"title": "Song 1", "artist": "Fleetwood Mac", "note": ""},  # over a week ago
        {"title": "Song 2", "artist": "Fleetwood Mac", "note": ""},
    ]
    sign_in(client, *ADMIN)
    put_on(client, make_station(client))
    assert upcoming(client) == ["Song 1", "Song 2"]
    asked = openai.asked_for("picks")[0]["input"]
    assert (
        "Heard in the office this past week, oldest first. Don't pick any of these, in any "
        "version:\nFleetwood Mac – Dreams\n\n"
    ) in asked


def test_the_ai_is_asked_again_when_too_many_picks_are_out(
    client: TestClient, openai: FakeOpenAI, settings: Settings, caplog
) -> None:
    played(settings, spotify_id("dreams"), "Dreams", "Fleetwood Mac", ago=60 * 60)
    openai.picks_in_turn = [
        [
            {"title": "Song 1", "artist": "Fleetwood Mac", "note": ""},
            {"title": "Dreams", "artist": "Fleetwood Mac", "note": ""},  # played an hour ago
            {"title": "Not On Spotify", "artist": "Nobody", "note": ""},
        ],
        FLEETWOOD[1:],
    ]
    sign_in(client, *ADMIN)
    put_on(client, make_station(client))
    assert upcoming(client) == ["Song 1", "Song 2", "Song 3"]

    first, again = (ask["input"] for ask in openai.asked_for("picks"))
    assert first.endswith("Pick 16 songs, in the order they should play.")
    assert "Your picks so far, which are in:\nFleetwood Mac – Song 1\n\n" in again
    out = "These are out, as they've been heard this week or are lined up:\nFleetwood Mac – Dreams"
    assert out in again
    assert "These couldn't be found on Spotify:\nNobody – Not On Spotify" in again
    assert again.endswith(
        "Pick 15 more songs, different from all of these, to play after your picks so far."
    )
    # The journal says what happened, and what it cost.
    assert (
        "Lunchtime Grooves: 8 of the AI's 14 picks kept, 1 heard this week or lined up, "
        "1 not on Spotify, after asking again. Tokens: 2,400 in (2,048 cached), 600 out"
    ) in caplog.text


def test_no_asking_again_once_spotify_pauses(
    client: TestClient, openai: FakeOpenAI, spotify: FakeSpotify
) -> None:
    openai.picks = FLEETWOOD
    spotify.busy = True
    sign_in(client, *ADMIN)
    put_on(client, make_station(client))
    assert len(openai.asked_for("picks")) == 1


def test_nor_another_version_of_a_song_a_request_played(
    client: TestClient, openai: FakeOpenAI, spotify: FakeSpotify, speakers
) -> None:
    spotify.tracks.append(spotify.track("fm3r", "Song 3 - Remastered", "Fleetwood Mac", ""))
    openai.picks = FLEETWOOD
    sign_in(client, *ADMIN)
    put_on(client, make_station(client))
    client.post("/api/playback/play").raise_for_status()
    client.post("/api/queue", json={"track_id": spotify_id("fm3r")}).raise_for_status()
    song_ends(client, speakers)
    assert playing(client) == "Song 3 - Remastered"
    assert upcoming(client)[:2] == ["Song 2", "Song 4"]


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
    openai.line = {"script": "Here's another."}
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
    assert slots[4]["line"] == "Here's another."
    second = openai.asked_for("dj_line")[1]["input"]
    assert "It's Tuesday 13 October, 10:13, morning." in second
    assert 'Just played: "Song 4" by Fleetwood Mac.' in second
    assert "Don't repeat yourself" in second and "- Here's another." in second

    # Nothing was kept: no notes on picks, and nothing is on.
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        assert db.execute("SELECT count(*) FROM pick_notes").fetchone() == (0,)
    assert queue(client)["source"] is None


def test_an_hour_with_the_dj_talking_every_few_minutes(client, openai: FakeOpenAI) -> None:
    openai.picks = HOUR_OF_SONGS
    openai.line = {"script": "Here's one."}
    sign_in(client, *ADMIN)
    slots = preview(client, dj=True, dj_name="Della", talk_every=10, talk_unit="minutes").json()[
        "slots"
    ]
    assert [index for index, slot in enumerate(slots) if slot["line"]] == [0, 3, 6, 9, 12, 15]


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


def test_a_station_can_crossfade_between_songs(client: TestClient, openai, speakers) -> None:
    openai.picks = FLEETWOOD
    sign_in(client, *ADMIN)
    station = make_station(client)
    assert station["crossfade"] is False
    put_on(client, station)
    client.post("/api/playback/play").raise_for_status()
    speakers.track_position = 190
    read_speakers(client)
    assert speakers.crossfade is False

    body = {"name": station["name"], "description": station["description"], "crossfade": True}
    client.put(f"/api/stations/{station['id']}", json=body).raise_for_status()
    assert speakers.crossfade is True  # straight away, as it's on

    # With nothing filling the gaps, nothing asks for it.
    client.delete("/api/source").raise_for_status()
    assert speakers.crossfade is False
