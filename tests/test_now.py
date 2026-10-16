from datetime import timedelta

from fastapi.testclient import TestClient

from tests.fakes import FakeSpeakers, spotify_id
from tests.helpers import ADMIN, read_speakers, sign_in
from tests.test_playlists import make, playing, queue, song_ends


def now(client: TestClient) -> dict:
    return client.get("/api/now").json()


def history(client: TestClient, **params) -> dict:
    return client.get("/api/history", params=params).json()


def lined_up(speakers: FakeSpeakers) -> list[str]:
    """What the speakers will play after the current song, by Spotify id."""
    return [item.uri for item in speakers.queue[speakers.position :]]


def put_on(client: TestClient, playlist: dict) -> None:
    client.post(f"/api/playlists/{playlist['id']}/play").raise_for_status()


# Switching


def test_a_switch_waits_for_the_current_song(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    fridays = make(client, "Fridays", ["fm1", "fm2"])
    mondays = make(client, "Mondays", ["fm4", "fm5"])
    put_on(client, fridays)
    client.post("/api/playback/play").raise_for_status()
    assert playing(client) == "Song 1"

    put_on(client, mondays)
    assert playing(client) == "Song 1"
    assert queue(client)["source"]["name"] == "Mondays"
    song_ends(client, speakers)
    assert playing(client) == "Song 4"


def test_a_switch_takes_back_the_song_already_lined_up(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    fridays = make(client, "Fridays", ["fm1", "fm2", "fm3"])
    mondays = make(client, "Mondays", ["fm4", "fm5"])
    put_on(client, fridays)
    client.post("/api/playback/play").raise_for_status()
    speakers.track_position = 190  # Song 2 goes to the speakers
    read_speakers(client)
    assert queue(client)["next"]["track"]["title"] == "Song 2"

    put_on(client, mondays)
    assert queue(client)["next"]["track"]["title"] == "Song 4"
    assert not any(spotify_id("fm2") in uri for uri in lined_up(speakers))
    speakers.song_ends()
    read_speakers(client)
    assert playing(client) == "Song 4"

    # Song 2 never played, so Fridays carries on from it.
    put_on(client, fridays)
    song_ends(client, speakers)
    assert playing(client) == "Song 2"


def test_a_playlist_carries_on_where_it_left_off(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    fridays = make(client, "Fridays", ["fm1", "fm2", "fm3", "fm4"])
    mondays = make(client, "Mondays", ["fm5", "dreams"])
    put_on(client, fridays)
    client.post("/api/playback/play").raise_for_status()
    song_ends(client, speakers)
    assert playing(client) == "Song 2"

    put_on(client, mondays)
    song_ends(client, speakers)
    assert playing(client) == "Song 5"
    put_on(client, fridays)
    song_ends(client, speakers)
    assert playing(client) == "Song 3"


def test_a_playlist_put_back_after_its_last_song_starts_afresh(client, speakers) -> None:
    sign_in(client, *ADMIN)
    fridays = make(client, "Fridays", ["fm1", "fm2"])
    mondays = make(client, "Mondays", ["fm4", "fm5"])
    put_on(client, fridays)
    client.post("/api/playback/play").raise_for_status()
    song_ends(client, speakers)
    assert playing(client) == "Song 2"

    put_on(client, mondays)
    song_ends(client, speakers)
    put_on(client, fridays)
    song_ends(client, speakers)
    assert playing(client) == "Song 1"


def test_putting_on_the_playlist_already_on_changes_nothing(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    fridays = make(client, "Fridays", ["fm1", "fm2", "fm3"])
    put_on(client, fridays)
    client.post("/api/playback/play").raise_for_status()
    song_ends(client, speakers)
    put_on(client, fridays)
    song_ends(client, speakers)
    assert playing(client) == "Song 3"


def test_a_request_lined_up_stays_through_a_switch(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    fridays = make(client, "Fridays", ["fm1", "fm2"])
    mondays = make(client, "Mondays", ["fm4"])
    put_on(client, fridays)
    client.post("/api/playback/play").raise_for_status()
    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()
    speakers.track_position = 190
    read_speakers(client)

    put_on(client, mondays)
    assert queue(client)["next"]["track"]["title"] == "Dreams"
    speakers.song_ends()
    read_speakers(client)
    assert playing(client) == "Dreams"
    song_ends(client, speakers)
    assert playing(client) == "Song 4"


def test_requests_only_comes_after_this_song_too(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    fridays = make(client, "Fridays", ["fm1", "fm2"])
    put_on(client, fridays)
    client.post("/api/playback/play").raise_for_status()
    speakers.track_position = 190
    read_speakers(client)
    assert queue(client)["next"] is not None

    assert client.delete("/api/source").status_code == 204
    assert queue(client)["next"] is None
    assert lined_up(speakers) == []
    assert now(client)["requests_only"] is True


# What's on, and what's played


def test_now_says_where_the_song_came_from(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    assert now(client)["on_air"] is None
    fridays = make(client, "Fridays", ["fm1", "fm2"])
    put_on(client, fridays)
    client.post("/api/playback/play").raise_for_status()
    body = now(client)
    assert body["on_air"] == "library"
    assert body["requests_only"] is False
    tile = next(p for p in body["playlists"] if p["name"] == "Fridays")
    assert (tile["on_air"], tile["filling"], tile["tracks"]) == (True, True, 2)

    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()
    song_ends(client, speakers)
    body = now(client)
    assert body["on_air"] == "queue"
    tile = next(p for p in body["playlists"] if p["name"] == "Fridays")
    assert (tile["on_air"], tile["filling"]) == (False, True)


def test_playlists_come_last_played_first(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    fridays = make(client, "Fridays", ["fm1", "fm2"])
    mondays = make(client, "Mondays", ["fm4"])
    make(client, "Aardvark", ["fm5"])
    # Nothing has played: Best Voted, then by name.
    assert [p["name"] for p in now(client)["playlists"]] == [
        "Best Voted",
        "Aardvark",
        "Fridays",
        "Mondays",
    ]

    put_on(client, mondays)
    client.post("/api/playback/play").raise_for_status()
    put_on(client, fridays)
    song_ends(client, speakers)
    names = [p["name"] for p in now(client)["playlists"]]
    assert names[:2] == ["Fridays", "Mondays"]
    assert now(client)["playlists"][0]["last_played_at"] is not None


def test_history_lists_todays_plays_and_where_they_came_from(client: TestClient, speakers):
    sign_in(client, *ADMIN)
    fridays = make(client, "Fridays", ["fm1", "fm2"])
    put_on(client, fridays)
    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()
    client.post("/api/playback/play").raise_for_status()
    song_ends(client, speakers)

    plays = history(client)["plays"]
    assert [p["track"]["title"] for p in plays] == ["Song 1", "Dreams"]
    assert plays[0]["playlist"] == "Fridays"
    assert plays[0]["requested_by"] is None
    assert plays[1]["requested_by"]["display_name"] == "Admin"
    assert plays[1]["playlist"] is None


def test_history_comes_a_page_at_a_time(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    put_on(client, make(client, "Fridays", ["fm1", "fm2", "fm3", "fm4"]))
    client.post("/api/playback/play").raise_for_status()
    for _ in range(3):
        song_ends(client, speakers)

    first = history(client, limit=3)
    assert [p["track"]["title"] for p in first["plays"]] == ["Song 4", "Song 3", "Song 2"]
    assert first["more"] is True
    rest = history(client, limit=3, before=first["plays"][-1]["id"])
    assert [p["track"]["title"] for p in rest["plays"]] == ["Song 1"]
    assert rest["more"] is False


def test_history_starts_afresh_each_day(client: TestClient, speakers, clock) -> None:
    sign_in(client, *ADMIN)
    put_on(client, make(client, "Fridays", ["fm1"]))
    client.post("/api/playback/play").raise_for_status()
    assert len(history(client)["plays"]) == 1
    clock.now += timedelta(days=3650)
    assert history(client)["plays"] == []
