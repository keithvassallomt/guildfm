from fastapi.testclient import TestClient

from tests.fakes import FakeOpenAI, spotify_id
from tests.helpers import ADMIN, sign_in
from tests.test_dj import lines, next_song, on_air

RUMOURS = spotify_id("rumours")
TUSK = spotify_id("tusk")


def queue_album(client: TestClient, album_id: str):
    return client.post("/api/queue/albums", json={"album_id": album_id})


def everything(queue: dict) -> list[dict]:
    """The queue's songs in order: playing, next, then waiting."""
    return [e for e in (queue["playing"], queue["next"]) if e] + queue["waiting"]


def test_curators_queue_a_whole_album_in_order(client: TestClient, people) -> None:
    sign_in(client, *people["curator"])
    response = queue_album(client, TUSK)
    assert response.status_code == 201
    body = response.json()
    assert body["added"] == 20  # its last song can't play here
    songs = everything(body["queue"])
    assert [e["track"]["title"] for e in songs] == [f"Song {n}" for n in range(1, 21)]
    assert {(e["requested_by"]["display_name"], e["album"]) for e in songs} == {("Curator", "Tusk")}
    assert body["queue"]["activity"][0]["text"] == "Curator queued Tusk by Fleetwood Mac (20 songs)"

    # It doesn't use up their requests.
    assert body["queue"]["mine"] == 0
    request = client.post("/api/queue", json={"track_id": spotify_id("dreams")})
    assert request.status_code == 201
    assert request.json()["mine"] == 1


def test_songs_already_queued_stay_where_they_are(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    client.post("/api/queue", json={"track_id": spotify_id("gyow")}).raise_for_status()
    sign_in(client, *people["curator"])
    body = queue_album(client, RUMOURS).json()
    assert body["added"] == 1
    songs = {e["track"]["title"]: e for e in everything(body["queue"])}
    assert songs["Go Your Own Way"]["requested_by"]["display_name"] == "User"
    assert songs["Go Your Own Way"]["album"] is None
    assert songs["Dreams"]["album"] == "Rumours"

    again = queue_album(client, RUMOURS)
    assert again.status_code == 409
    assert "already in the queue" in again.json()["detail"]


def test_explicit_songs_are_left_out_when_not_allowed(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    client.patch("/api/settings", json={"allow_explicit": False}).raise_for_status()
    response = queue_album(client, spotify_id("damn"))
    assert response.status_code == 409
    assert "None of that album's songs" in response.json()["detail"]


def test_only_curators_and_admins_queue_albums(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    assert queue_album(client, RUMOURS).status_code == 403


def test_the_dj_names_the_requester_once_per_album(client, openai: FakeOpenAI, speakers, people):
    sign_in(client, *ADMIN)
    on_air(client, openai, talk_every=10)
    next_song(client, speakers)  # the DJ says hello with Song 2
    sign_in(client, *people["curator"])
    queue_album(client, RUMOURS).raise_for_status()

    next_song(client, speakers)  # Dreams, the album's first song
    assert len(lines(openai)) == 2
    assert (
        "Curator put on the whole of the album Rumours, starting with this. Say their name."
        in lines(openai)[-1]
    )
    next_song(client, speakers)  # Go Your Own Way: not a shout-out, and not time to talk
    assert len(lines(openai)) == 2
