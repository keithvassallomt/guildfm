from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from tests.fakes import FakeOpenAI, FakeSpeakers, mp3, spotify_id
from tests.helpers import ADMIN, read_speakers, sign_in

LONDON = ZoneInfo("Europe/London")
FLEETWOOD = [
    {"title": f"Song {n}", "artist": "Fleetwood Mac", "note": f"Note {n}"} for n in range(1, 13)
]
# Nine songs of 200 seconds: half an hour.
MORNING = ["dreams", "gyow"] + [f"fm{n}" for n in range(13, 20)]


@pytest.fixture(autouse=True)
def no_waiting(client: TestClient) -> None:
    """Clips play instantly here."""

    async def nap(seconds: float) -> None:
        pass

    client.app.state.announcer.sleep = nap


def at(clock, hour: int, minute: int, second: int = 0) -> None:
    """Set the time in the office, a Tuesday."""
    clock.now = datetime(2026, 10, 13, hour, minute, second, tzinfo=LONDON)


def minutes(clock_text: str) -> int:
    hours, mins = clock_text.split(":")
    return int(hours) * 60 + int(mins)


def make_station(client: TestClient, openai: FakeOpenAI, **fields) -> dict:
    openai.picks = FLEETWOOD
    body = {"name": "Lunchtime Grooves", "description": "Upbeat soul.", **fields}
    response = client.post("/api/stations", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def make_playlist(client: TestClient, name: str = "Morning Coffee") -> dict:
    playlist = client.post("/api/playlists", json={"name": name}).json()
    for song in MORNING:
        client.post(
            f"/api/playlists/{playlist['id']}/tracks", json={"track_id": spotify_id(song)}
        ).raise_for_status()
    return playlist


def show(station: dict, start: str, end: str) -> dict:
    return {"station_id": station["id"], "start": minutes(start), "end": minutes(end)}


def playlist_slot(playlist: dict, start: str, end: str) -> dict:
    return {"playlist_id": playlist["id"], "start": minutes(start), "end": minutes(end)}


def make_lineup(client: TestClient, slots: list[dict], name: str = "Office Day"):
    return client.post("/api/lineups", json={"name": name, "description": "A day.", "slots": slots})


def put_on(client: TestClient, lineup: dict) -> None:
    client.post(f"/api/lineups/{lineup['id']}/play").raise_for_status()
    client.portal.call(client.app.state.radio.settle)


def queue(client: TestClient) -> dict:
    return client.get("/api/queue").json()


def now(client: TestClient) -> dict:
    return client.get("/api/now").json()


def line_up_next(client: TestClient, speakers: FakeSpeakers) -> None:
    """Ten seconds of the song left: the next one goes to the speakers."""
    speakers.track_position = 190
    read_speakers(client)
    client.portal.call(client.app.state.radio.settle)


def next_song(client: TestClient, speakers: FakeSpeakers) -> None:
    speakers.song_ends()
    read_speakers(client)


# Planning


def test_curators_plan_lineups(client: TestClient, people, openai) -> None:
    sign_in(client, *people["curator"])
    station = make_station(client, openai)
    playlist = make_playlist(client)
    response = make_lineup(
        client, [playlist_slot(playlist, "08:00", "08:30"), show(station, "09:00", "10:00")]
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert [(slot["kind"], slot["name"], slot["start"]) for slot in body["slots"]] == [
        ("playlist", "Morning Coffee", 480),
        ("show", "Lunchtime Grooves", 540),
    ]
    assert body["slots"][0]["minutes"] == 30
    assert body["made_by"] == "Curator"
    assert [lineup["name"] for lineup in client.get("/api/lineups").json()] == ["Office Day"]

    sign_in(client, *people["user"])
    assert client.get("/api/lineups").status_code == 403
    assert make_lineup(client, []).status_code == 403


def test_slots_are_checked(client: TestClient, openai) -> None:
    sign_in(client, *ADMIN)
    station = make_station(client, openai)
    playlist = make_playlist(client)
    overlapping = [show(station, "09:00", "10:00"), show(station, "09:45", "11:00")]
    assert make_lineup(client, overlapping).status_code == 422
    assert (
        make_lineup(client, [{**show(station, "09:00", "10:00"), "start": 547}]).status_code == 422
    )
    response = make_lineup(client, [playlist_slot(playlist, "09:00", "10:00")])
    assert response.status_code == 409
    assert "isn't that long" in response.json()["detail"]
    assert make_lineup(client, [{"station_id": 999, "start": 540, "end": 600}]).status_code == 409


def test_the_editor_offers_the_day_and_what_to_put_on_it(client: TestClient, openai) -> None:
    sign_in(client, *ADMIN)
    make_station(client, openai, dj=True, dj_name="Della", voice="ash")
    make_playlist(client)
    choices = client.get("/api/lineups/choices").json()
    assert choices["day"] == {"start": 480, "end": 1080}  # weekdays, 08:00 to 18:00
    assert ("Lunchtime Grooves", "Della") in [(s["name"], s["dj_name"]) for s in choices["shows"]]
    # Best Voted is empty, so too short for a slot.
    assert [(p["name"], p["minutes"]) for p in choices["playlists"]] == [("Morning Coffee", 30)]


def test_a_lineup_gets_a_cover(client: TestClient, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    body = make_lineup(client, []).json()
    client.portal.call(client.app.state.covers.settle)
    assert client.get(f"/api/lineups/{body['id']}").json()["art_url"].startswith("/media/covers/")
    assert "a line-up for an office's radio" in openai.images[-1]["prompt"]


# Playing


def test_a_lineup_follows_the_clock(client: TestClient, openai, speakers, clock) -> None:
    sign_in(client, *ADMIN)
    station = make_station(client, openai)
    playlist = make_playlist(client)
    lineup = make_lineup(
        client, [show(station, "09:30", "10:15"), playlist_slot(playlist, "10:15", "10:45")]
    ).json()
    at(clock, 10, 0)
    put_on(client, lineup)
    client.post("/api/playback/play").raise_for_status()
    assert queue(client)["playing"]["station"] == "Lunchtime Grooves"

    # The next song would start at 10:14:50, still the show's.
    at(clock, 10, 14, 40)
    line_up_next(client, speakers)
    assert queue(client)["next"]["station"] == "Lunchtime Grooves"
    next_song(client, speakers)

    # This one would start at 10:15:05: the playlist's, the first song change after 10:15.
    at(clock, 10, 14, 55)
    line_up_next(client, speakers)
    assert queue(client)["next"]["playlist"] == "Morning Coffee"
    body = now(client)
    assert body["lineups"][0]["on"] is True
    tiles = {tile["name"]: tile for tile in body["playlists"]}
    assert tiles["Morning Coffee"]["in_lineup"] is True
    assert tiles["Morning Coffee"]["filling"] is False  # the line-up fills the gaps

    # Past 10:45 there's a gap, so AI picks, as "When the queue runs out" says.
    next_song(client, speakers)
    at(clock, 10, 44, 55)
    line_up_next(client, speakers)
    body = now(client)
    assert body["gap"] == "AI picks"
    assert {tile["name"]: tile["in_lineup"] for tile in body["stations"]}["AI picks"] is True


def test_now_playing_shows_the_lineup_on_air(client: TestClient, openai, speakers, clock) -> None:
    sign_in(client, *ADMIN)
    station = make_station(client, openai)
    lineup = make_lineup(client, [show(station, "09:00", "11:00")]).json()
    at(clock, 10, 5)
    put_on(client, lineup)
    client.post("/api/playback/play").raise_for_status()
    body = now(client)
    assert body["on_air"] == "lineups"
    assert body["minute"] == 605
    assert body["day"] == {"start": 480, "end": 1080}
    station_tile = next(tile for tile in body["stations"] if tile["name"] == "Lunchtime Grooves")
    assert (station_tile["on_air"], station_tile["in_lineup"]) == (False, True)


def test_picking_something_by_hand_ends_the_lineup(client: TestClient, openai, clock) -> None:
    sign_in(client, *ADMIN)
    station = make_station(client, openai)
    playlist = make_playlist(client)
    lineup = make_lineup(client, [show(station, "09:00", "11:00")]).json()
    at(clock, 10, 0)
    put_on(client, lineup)
    # Even the station the line-up is playing: picked by hand, it's on by itself.
    client.post(f"/api/stations/{station['id']}/play").raise_for_status()
    assert now(client)["lineups"][0]["on"] is False
    put_on(client, lineup)
    client.post(f"/api/playlists/{playlist['id']}/play").raise_for_status()
    body = now(client)
    assert body["lineups"][0]["on"] is False
    assert {tile["name"]: tile["filling"] for tile in body["playlists"]}["Morning Coffee"] is True


def test_deleting_the_station_on_leaves_a_gap(client: TestClient, openai, clock) -> None:
    sign_in(client, *ADMIN)
    station = make_station(client, openai)
    lineup = make_lineup(client, [show(station, "09:00", "11:00")]).json()
    at(clock, 10, 0)
    put_on(client, lineup)
    client.delete(f"/api/stations/{station['id']}").raise_for_status()
    body = now(client)
    assert body["lineups"][0]["on"] is True
    assert body["lineups"][0]["slots"] == []
    assert {tile["name"]: tile["in_lineup"] for tile in body["stations"]}["AI picks"] is True


def test_deleting_the_lineup_on(client: TestClient, openai, clock) -> None:
    sign_in(client, *ADMIN)
    station = make_station(client, openai)
    lineup = make_lineup(client, [show(station, "09:00", "11:00")]).json()
    at(clock, 10, 0)
    put_on(client, lineup)
    client.delete(f"/api/lineups/{lineup['id']}").raise_for_status()
    body = now(client)
    assert body["lineups"] == []
    assert not any(tile["in_lineup"] for tile in body["stations"])


def test_a_show_opens_with_its_ident_and_its_dj(client: TestClient, openai, speakers, clock):
    sign_in(client, *ADMIN)
    station = make_station(
        client, openai, dj=True, dj_name="Della", personality="Warm.", voice="ash"
    )
    client.post(
        "/api/jingles",
        params={"name": "Grooves sting", "station_id": station["id"]},
        content=mp3(9.0),
        headers={"content-type": "audio/mpeg"},
    ).raise_for_status()
    playlist = make_playlist(client)
    lineup = make_lineup(
        client, [playlist_slot(playlist, "09:45", "10:15"), show(station, "10:15", "11:00")]
    ).json()
    at(clock, 10, 0)
    put_on(client, lineup)
    client.post("/api/playback/play").raise_for_status()

    openai.line = {"script": "Lunchtime Grooves, with me until eleven."}
    at(clock, 10, 14, 55)
    line_up_next(client, speakers)  # the show's first songs are picked, then the first lined up
    client.portal.call(client.app.state.dj.settle)
    assert queue(client)["next"]["station"] == "Lunchtime Grooves"
    prompt = openai.asked_for("dj_line")[-1]["input"]
    assert (
        "Your show, Lunchtime Grooves, part of the Office Day line-up, starts now and runs "
        "until 11:00." in prompt
    )
    client.portal.call(client.app.state.announcer.tick)
    assert any("/media/jingles/" in item.uri for item in speakers.queue)


def test_a_lineup_stays_on_after_a_restart(start, openai, speakers, clock) -> None:
    with start() as client:
        sign_in(client, *ADMIN)
        station = make_station(client, openai)
        lineup = make_lineup(client, [show(station, "09:00", "11:00")]).json()
        at(clock, 10, 0)
        put_on(client, lineup)
    with start() as client:
        sign_in(client, *ADMIN)
        assert now(client)["lineups"][0]["on"] is True


def test_a_show_picks_its_first_songs_before_it_starts(client, openai, speakers, clock) -> None:
    sign_in(client, *ADMIN)
    station = make_station(client, openai)
    playlist = make_playlist(client)
    lineup = make_lineup(
        client, [playlist_slot(playlist, "09:45", "10:15"), show(station, "10:15", "11:00")]
    ).json()
    at(clock, 10, 0)
    put_on(client, lineup)
    client.post("/api/playback/play").raise_for_status()
    assert openai.asked_for("picks") == []

    # Ten minutes or less before the show, its station picks.
    at(clock, 10, 6)
    line_up_next(client, speakers)
    assert len(openai.asked_for("picks")) == 1
    next_song(client, speakers)

    # At the hand-over its first song is lined up straight away, without asking again.
    at(clock, 10, 14, 55)
    speakers.track_position = 190
    read_speakers(client)
    assert queue(client)["next"]["station"] == "Lunchtime Grooves"
    assert len(openai.asked_for("picks")) == 1
