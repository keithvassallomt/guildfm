import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from guildfm.config import Settings
from tests.fakes import spotify_id
from tests.helpers import ADMIN, PASSWORD, register, sign_in

KIOSK = ("kiosk", PASSWORD)


@pytest.fixture
def kiosk(client: TestClient, people) -> tuple[str, str]:
    """A kiosk account, made from a sign-up by an admin. Leaves the client signed in as it."""
    account = register(client, "kiosk")
    sign_in(client, *ADMIN)
    client.patch(f"/api/users/{account['id']}", json={"role": "kiosk"}).raise_for_status()
    sign_in(client, *KIOSK)
    return KIOSK


def request(client: TestClient, name: str):
    return client.post("/api/queue", json={"track_id": spotify_id(name)})


def queue(client: TestClient) -> dict:
    return client.get("/api/queue").json()


def entry_for(client: TestClient, title: str) -> dict:
    return next(e for e in queue(client)["waiting"] if e["track"]["title"] == title)


def vote(client: TestClient, title: str, value: int):
    return client.post(f"/api/queue/{entry_for(client, title)['id']}/vote", json={"value": value})


def sql(settings: Settings, statement: str, *args) -> None:
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        db.execute(statement, args)


def test_the_kiosk_sees_its_places_and_look(client: TestClient, kiosk) -> None:
    body = queue(client)
    assert body["kiosk"].pop("now")  # the server's time, for the screen's countdowns
    assert body["kiosk"] == {
        "places": 8,
        "used": 0,
        "break_until": None,
        "break_seconds": 180,
        "votes": 2,
        "undo_seconds": 10,
        "theme": "dark",
    }
    # People don't get any of that.
    sign_in(client, "user", PASSWORD)
    assert queue(client)["kiosk"] is None


def test_eight_requests_then_a_break(client: TestClient, kiosk, settings: Settings) -> None:
    # No request cap: it has places instead.
    for number in range(1, 8):
        assert request(client, f"fm{number}").status_code == 201
    body = queue(client)
    assert body["kiosk"]["used"] == 7
    assert body["kiosk"]["break_until"] is None
    assert body["activity"][0]["text"] == "Someone at the kiosk requested Song 7"

    # The eighth takes the last place and starts a three-minute break.
    started = time.time()
    body = request(client, "fm8").json()
    assert body["kiosk"]["used"] == 8
    assert body["kiosk"]["break_until"] is not None
    refused = request(client, "fm9")
    assert refused.status_code == 409
    assert refused.json()["detail"] == "The kiosk is on a break. Try again when the countdown ends."
    assert vote(client, "Song 1", 1).status_code == 409

    # Once it's over, every place is free again.
    sql(settings, "UPDATE users SET kiosk_break_until = ? WHERE username = 'kiosk'", started + 1)
    time.sleep(1.1)
    body = queue(client)
    assert body["kiosk"]["used"] == 0
    assert body["kiosk"]["break_until"] is None
    assert request(client, "fm9").status_code == 201


def test_a_song_leaving_the_queue_gives_its_place_back(client: TestClient, kiosk) -> None:
    request(client, "fm1")
    request(client, "fm2")
    assert queue(client)["kiosk"]["used"] == 2
    sign_in(client, "curator", PASSWORD)
    client.delete(f"/api/queue/{entry_for(client, 'Song 1')['id']}").raise_for_status()
    sign_in(client, *KIOSK)
    assert queue(client)["kiosk"]["used"] == 1


def test_the_places_are_a_setting(client: TestClient, kiosk) -> None:
    sign_in(client, *ADMIN)
    client.patch(
        "/api/settings", json={"kiosk_places": 2, "kiosk_theme": "light"}
    ).raise_for_status()
    sign_in(client, *KIOSK)
    request(client, "fm1")
    body = request(client, "fm2").json()
    assert body["kiosk"]["places"] == 2
    assert body["kiosk"]["theme"] == "light"
    assert body["kiosk"]["break_until"] is not None


def test_the_kiosk_counts_as_two_voters_at_most(client: TestClient, kiosk) -> None:
    sign_in(client, "user", PASSWORD)
    request(client, "fm1")
    sign_in(client, *KIOSK)
    vote(client, "Song 1", 1)
    body = vote(client, "Song 1", 1).json()
    song = body["waiting"][0]
    assert (song["up"], song["kiosk_up"], song["my_vote"]) == (2, 2, 0)
    third = vote(client, "Song 1", 1)
    assert third.status_code == 409
    assert third.json()["detail"] == "The kiosk has given that song both its thumbs up."
    assert vote(client, "Song 1", 0).status_code == 409  # it can't take one back

    # Everyone else still has their one vote.
    sign_in(client, "curator", PASSWORD)
    song = vote(client, "Song 1", 1).json()["waiting"][0]
    assert (song["up"], song["score"], song["kiosk_up"]) == (3, 3, 0)


def test_the_kiosk_cant_take_out_a_request_on_its_own(client: TestClient, kiosk) -> None:
    sign_in(client, "user", PASSWORD)
    request(client, "fm1")
    sign_in(client, *KIOSK)
    vote(client, "Song 1", -1)
    song = vote(client, "Song 1", -1).json()["waiting"][0]
    assert (song["down"], song["score"]) == (2, -2)
    # One more thumbs down from someone reaches the limit of -3.
    sign_in(client, "curator", PASSWORD)
    assert vote(client, "Song 1", -1).json()["waiting"] == []


def test_a_request_can_be_taken_back_straight_away(client: TestClient, kiosk, settings) -> None:
    song = request(client, "fm1").json()["waiting"][0]
    assert song["undo_until"] is not None
    body = client.delete(f"/api/queue/{song['id']}").json()
    assert body["waiting"] == []
    assert body["activity"][0]["text"] == "Someone at the kiosk took Song 1 back"

    # Not once the moment has passed.
    request(client, "fm2")
    sql(settings, "UPDATE queue SET added_at = added_at - 20")
    song = entry_for(client, "Song 2")
    assert song["undo_until"] is None
    late = client.delete(f"/api/queue/{song['id']}")
    assert late.status_code == 409
    assert late.json()["detail"] == "It's too late to take that one back."


def test_taking_back_the_eighth_ends_the_break(client: TestClient, kiosk) -> None:
    for number in range(1, 9):
        request(client, f"fm{number}")
    assert queue(client)["kiosk"]["break_until"] is not None
    client.delete(f"/api/queue/{entry_for(client, 'Song 8')['id']}").raise_for_status()
    body = queue(client)
    assert (body["kiosk"]["used"], body["kiosk"]["break_until"]) == (7, None)
    assert request(client, "fm9").status_code == 201


def test_the_kiosk_only_takes_back_its_own(client: TestClient, kiosk) -> None:
    sign_in(client, "user", PASSWORD)
    request(client, "fm1")
    sign_in(client, *KIOSK)
    response = client.delete(f"/api/queue/{entry_for(client, 'Song 1')['id']}")
    assert response.status_code == 403


def test_the_kiosk_takes_turns_as_one_person(client: TestClient, kiosk) -> None:
    request(client, "fm1")
    request(client, "fm2")
    sign_in(client, "user", PASSWORD)
    request(client, "fm3")
    titles = [e["track"]["title"] for e in queue(client)["waiting"]]
    assert titles == ["Song 1", "Song 3", "Song 2"]


def test_what_the_kiosk_cant_do(client: TestClient, kiosk) -> None:
    request(client, "fm1")
    song = entry_for(client, "Song 1")
    assert client.post(f"/api/queue/{song['id']}/move", json={"position": 1}).status_code == 403
    album = client.post("/api/queue/albums", json={"album_id": spotify_id("tusk")})
    assert album.status_code == 403
    thumb = client.post("/api/source/vote", json={"track_id": spotify_id("fm2"), "down": True})
    assert thumb.status_code == 403
    assert client.patch("/api/settings", json={"kiosk_places": 30}).status_code == 403
    assert client.post("/api/playback/skip").status_code == 403


def test_the_office_favourites_come_from_best_voted(client: TestClient, kiosk) -> None:
    response = client.get("/api/queue/favourites")
    assert response.status_code == 200
    assert response.json() == []
