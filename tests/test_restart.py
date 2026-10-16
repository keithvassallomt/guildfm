from fastapi.testclient import TestClient

from guildfm.speakers import spotify_item
from tests.fakes import spotify_id
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
        assert status(client) == "stopped"
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
        assert status(client) == "stopped"


def test_stopped_stays_stopped_after_a_restart(start, speakers) -> None:
    with start() as client:
        playing_two_songs(client, speakers)
        client.post("/api/playback/stop").raise_for_status()

    with start() as client:
        sign_in(client, *ADMIN)
        assert status(client) == "stopped"
