from fastapi.testclient import TestClient

from guildfm.speakers import spotify_item
from tests.fakes import mp3, spotify_id
from tests.helpers import ADMIN, read_speakers, sign_in


def request(client: TestClient, name: str) -> None:
    client.post("/api/queue", json={"track_id": spotify_id(name)}).raise_for_status()


def status(client: TestClient) -> str:
    return client.get("/api/playback").json()["status"]


def queue(client: TestClient) -> dict:
    return client.get("/api/queue").json()


def playing_two_songs(client: TestClient, speakers) -> None:
    """Song 1 playing, Song 2 already lined up on the speakers."""
    sign_in(client, *ADMIN)
    request(client, "fm1")
    request(client, "fm2")
    client.post("/api/playback/play").raise_for_status()
    speakers.track_position = 190
    read_speakers(client)


def test_after_a_restart_guildfm_carries_on_driving_the_speakers(start, speakers) -> None:
    with start() as client:
        playing_two_songs(client, speakers)

    with start() as client:
        sign_in(client, *ADMIN)
        assert status(client) == "playing"
        body = queue(client)
        assert body["playing"]["track"]["title"] == "Song 1"
        assert body["next"]["track"]["title"] == "Song 2"
        speakers.song_ends()
        read_speakers(client)
        assert queue(client)["playing"]["track"]["title"] == "Song 2"


def test_a_queue_built_in_the_sonos_app_isnt_mistaken_for_guildfms(start, speakers) -> None:
    with start() as client:
        playing_two_songs(client, speakers)
    speakers.take_over([spotify_item(spotify_id("dreams"), sid=9, sn=1)])

    with start() as client:
        sign_in(client, *ADMIN)
        assert status(client) == "overridden"
        body = queue(client)
        assert body["playing"] is None
        assert body["next"] is None
        assert [entry["track"]["title"] for entry in body["waiting"]] == ["Song 2"]


def test_radio_from_the_sonos_app_isnt_picked_up(start, speakers) -> None:
    with start() as client:
        playing_two_songs(client, speakers)
    speakers.someone_plays_radio()

    with start() as client:
        sign_in(client, *ADMIN)
        assert status(client) == "overridden"


def test_stopped_stays_stopped_after_a_restart(start, speakers) -> None:
    with start() as client:
        playing_two_songs(client, speakers)
        client.post("/api/playback/stop").raise_for_status()

    with start() as client:
        sign_in(client, *ADMIN)
        assert status(client) == "stopped"


def test_why_songs_were_picked_and_their_jingles_survive_a_restart(start, speakers, openai):
    openai.picks = [
        {"title": f"Song {n}", "artist": "Fleetwood Mac", "note": f"Note {n}", "ident": "none"}
        for n in range(1, 13)
    ]
    openai.picks[1]["ident"] = "system"  # a jingle before Song 2
    openai.line = {"script": "Here's Song 2."}
    with start() as client:
        sign_in(client, *ADMIN)
        client.post(
            "/api/jingles",
            params={"name": "GuildFM sting"},
            content=mp3(9.0),
            headers={"content-type": "audio/mpeg"},
        ).raise_for_status()
        body = {
            "name": "Lunchtime Grooves",
            "description": "Upbeat soul.",
            "dj": True,
            "dj_name": "Della",
            "personality": "Warm northern host.",
            "voice": "ash",
        }
        station = client.post("/api/stations", json=body).json()
        client.post(f"/api/stations/{station['id']}/play").raise_for_status()
        client.portal.call(client.app.state.radio.settle)
        client.post("/api/playback/play").raise_for_status()

    with start() as client:
        speakers.track_position = 190
        read_speakers(client)  # Song 2 is lined up
        client.portal.call(client.app.state.dj.settle)
        client.portal.call(client.app.state.announcer.tick)
    assert "Why it was picked: Note 2" in openai.asked_for("dj_line")[-1]["input"]
    assert any("/media/jingles/" in item.uri for item in speakers.queue)


def test_the_dj_remembers_what_it_said_after_a_restart(start, speakers, openai) -> None:
    openai.picks = [
        {"title": f"Song {n}", "artist": "Fleetwood Mac", "note": f"Note {n}"} for n in range(1, 13)
    ]
    openai.line = {"script": "First up, Song 2."}
    with start() as client:
        sign_in(client, *ADMIN)
        body = {
            "name": "Lunchtime Grooves",
            "description": "Upbeat soul.",
            "dj": True,
            "dj_name": "Della",
            "personality": "Warm northern host.",
            "voice": "ash",
            "talk_every": 2,
        }
        station = client.post("/api/stations", json=body).json()
        client.post(f"/api/stations/{station['id']}/play").raise_for_status()
        client.portal.call(client.app.state.radio.settle)
        client.post("/api/playback/play").raise_for_status()
        speakers.track_position = 190
        read_speakers(client)  # Song 2 lined up: the DJ talks, as the station has just come on
        client.portal.call(client.app.state.dj.settle)
        speakers.song_ends()
        read_speakers(client)

    def lined_up_after_a_restart() -> None:
        with start() as client:
            speakers.track_position = 190
            read_speakers(client)
            client.portal.call(client.app.state.dj.settle)
            speakers.song_ends()
            read_speakers(client)

    lined_up_after_a_restart()  # Song 3: one song since it talked, so it waits
    assert len(openai.asked_for("dj_line")) == 1
    lined_up_after_a_restart()  # Song 4: two songs, so it talks, knowing what it said
    prompt = openai.asked_for("dj_line")[-1]["input"]
    assert len(openai.asked_for("dj_line")) == 2
    assert "- First up, Song 2." in prompt
