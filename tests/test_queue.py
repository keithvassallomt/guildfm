import sqlite3

import pytest
from fastapi.testclient import TestClient

from guildfm.config import Settings
from guildfm.speakers import SpeakersRefused
from tests.fakes import FakeSpeakers, spotify_id
from tests.helpers import ADMIN, read_speakers, register, sign_in


def request(client: TestClient, name: str):
    return client.post("/api/queue", json={"track_id": spotify_id(name)})


def titles(queue: dict) -> list[str]:
    return [entry["track"]["title"] for entry in queue["waiting"]]


def queue(client: TestClient) -> dict:
    return client.get("/api/queue").json()


def vote(client: TestClient, entry: dict, value: int):
    return client.post(f"/api/queue/{entry['id']}/vote", json={"value": value})


def entry_for(client: TestClient, title: str) -> dict:
    return next(e for e in queue(client)["waiting"] if e["track"]["title"] == title)


def set_pref(settings: Settings, key: str, value: str) -> None:
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))


# Requesting


def test_requesting_a_song(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    response = request(client, "dreams")
    assert response.status_code == 201
    body = response.json()
    assert titles(body) == ["Dreams"]
    entry = body["waiting"][0]
    assert entry["requested_by"]["display_name"] == "User"
    assert entry["mine"] is True
    assert body["mine"] == 1
    assert body["request_cap"] == 5
    assert body["activity"][0]["text"] == "User requested Dreams"


def test_requests_need_signing_in(client: TestClient) -> None:
    assert request(client, "dreams").status_code == 401


def test_a_song_can_only_be_queued_once(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    request(client, "dreams")
    sign_in(client, *people["curator"])
    response = request(client, "dreams")
    assert response.status_code == 409
    assert response.json()["detail"] == "That song is already in the queue."


def test_requests_per_person_are_capped(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    for number in range(1, 6):
        assert request(client, f"fm{number}").status_code == 201
    response = request(client, "fm6")
    assert response.status_code == 409
    assert "5 requests in the queue already" in response.json()["detail"]
    # Someone else still can.
    sign_in(client, *people["curator"])
    assert request(client, "fm6").status_code == 201


def test_admins_have_no_cap(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    for number in range(1, 8):
        assert request(client, f"fm{number}").status_code == 201


def test_the_cap_is_a_setting(client: TestClient, people, settings: Settings) -> None:
    set_pref(settings, "request_cap", "1")
    sign_in(client, *people["user"])
    request(client, "fm1")
    assert request(client, "fm2").status_code == 409


def test_songs_not_searched_for_are_looked_up(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    assert request(client, "gyow").status_code == 201
    assert client.post("/api/queue", json={"track_id": spotify_id("nope")}).status_code == 404


def test_explicit_songs_cant_be_requested_when_turned_off(client, people, settings) -> None:
    set_pref(settings, "allow_explicit", "false")
    sign_in(client, *people["user"])
    response = request(client, "humble")
    assert response.status_code == 403
    assert response.json()["detail"] == "Explicit tracks are turned off."


def test_search_shows_whats_queued(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    request(client, "dreams")
    tracks = client.get("/api/search", params={"q": "fleetwood"}).json()["tracks"]
    found = {track["title"]: track["queued"] for track in tracks}
    assert found["Dreams"] is True
    assert found["Go Your Own Way"] is False


# Voting


def test_votes_order_the_queue(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    request(client, "fm1")
    request(client, "fm2")
    request(client, "fm3")
    assert titles(queue(client)) == ["Song 1", "Song 2", "Song 3"]

    vote(client, entry_for(client, "Song 3"), 1)
    sign_in(client, *people["curator"])
    vote(client, entry_for(client, "Song 3"), 1)
    vote(client, entry_for(client, "Song 2"), 1)
    body = queue(client)
    assert titles(body) == ["Song 3", "Song 2", "Song 1"]
    assert [e["score"] for e in body["waiting"]] == [2, 1, 0]
    assert body["waiting"][0]["my_vote"] == 1
    assert body["waiting"][2]["my_vote"] == 0


def test_one_vote_each_which_can_change_or_be_taken_back(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    request(client, "fm1")
    entry = entry_for(client, "Song 1")
    vote(client, entry, 1)
    vote(client, entry, 1)
    assert entry_for(client, "Song 1")["score"] == 1
    vote(client, entry, -1)
    assert entry_for(client, "Song 1")["score"] == -1
    vote(client, entry, 0)
    assert entry_for(client, "Song 1")["score"] == 0


def test_enough_thumbs_down_removes_a_request(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    request(client, "fm1")
    entry = entry_for(client, "Song 1")
    for name in ("dan", "eve", "fay"):
        register(client, name)
        response = vote(client, entry, -1)
    body = response.json()
    assert titles(body) == []
    assert body["activity"][0]["text"] == "Song 1 was removed after too many thumbs down"


def test_the_downvote_threshold_is_a_setting(client: TestClient, people, settings) -> None:
    set_pref(settings, "downvote_threshold", "-1")
    sign_in(client, *people["user"])
    request(client, "fm1")
    assert titles(vote(client, entry_for(client, "Song 1"), -1).json()) == []


# Removing and moving


def test_you_can_remove_your_own_request_but_not_others(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    request(client, "fm1")
    mine = entry_for(client, "Song 1")
    sign_in(client, *people["curator"])
    request(client, "fm2")
    theirs = entry_for(client, "Song 2")

    sign_in(client, *people["user"])
    assert client.delete(f"/api/queue/{theirs['id']}").status_code == 403
    assert titles(client.delete(f"/api/queue/{mine['id']}").json()) == ["Song 2"]


def test_curators_remove_anyones_request(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    request(client, "fm1")
    sign_in(client, *people["curator"])
    body = client.delete(f"/api/queue/{entry_for(client, 'Song 1')['id']}").json()
    assert titles(body) == []
    assert body["activity"][0]["text"] == "Curator took Song 1 out of the queue"


def test_curators_move_requests_and_votes_dont_move_them_back(client, people) -> None:
    sign_in(client, *people["user"])
    for number in (1, 2, 3):
        request(client, f"fm{number}")
    sign_in(client, *people["curator"])
    song3 = entry_for(client, "Song 3")
    client.post(f"/api/queue/{song3['id']}/move", json={"position": 2})
    body = client.post(f"/api/queue/{song3['id']}/move", json={"position": 1}).json()
    assert titles(body) == ["Song 3", "Song 1", "Song 2"]
    assert body["waiting"][0]["pinned"] is True
    assert body["activity"][0]["text"] == "Curator moved Song 3 up"

    for name in ("dan", "eve"):
        register(client, name)
        vote(client, entry_for(client, "Song 2"), 1)
    assert titles(queue(client)) == ["Song 3", "Song 2", "Song 1"]


def test_dragging_keeps_every_placed_request_where_it_was_dropped(client, people) -> None:
    sign_in(client, *people["user"])
    for number in (1, 2, 3, 4):
        request(client, f"fm{number}")
    sign_in(client, *people["curator"])

    def drag(title: str, position: int) -> list[str]:
        entry = entry_for(client, title)
        return titles(
            client.post(f"/api/queue/{entry['id']}/move", json={"position": position}).json()
        )

    assert drag("Song 4", 1) == ["Song 4", "Song 1", "Song 2", "Song 3"]
    assert drag("Song 2", 1) == ["Song 2", "Song 4", "Song 1", "Song 3"]
    assert drag("Song 1", 99) == ["Song 2", "Song 4", "Song 3", "Song 1"]
    # Songs nobody placed still follow the votes, in the gaps between placed ones.
    for name in ("dan", "eve"):
        register(client, name)
        vote(client, entry_for(client, "Song 3"), -1)
    assert titles(queue(client)) == ["Song 2", "Song 4", "Song 3", "Song 1"]


def test_only_curators_move_requests(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    request(client, "fm1")
    entry = entry_for(client, "Song 1")
    response = client.post(f"/api/queue/{entry['id']}/move", json={"position": 1})
    assert response.status_code == 403


def test_deleting_someone_removes_their_requests_and_votes(client: TestClient, people) -> None:
    dan = register(client, "dan")
    request(client, "fm1")
    sign_in(client, *people["user"])
    request(client, "fm2")
    sign_in(client, "dan")
    vote(client, entry_for(client, "Song 2"), 1)

    sign_in(client, *ADMIN)
    client.delete(f"/api/users/{dan['id']}").raise_for_status()
    body = queue(client)
    assert titles(body) == ["Song 2"]
    assert body["waiting"][0]["score"] == 0


# Keeping the speakers fed


def test_the_queue_plays_through(client: TestClient, people, speakers: FakeSpeakers, settings):
    sign_in(client, *people["user"])
    request(client, "fm1")
    request(client, "fm2")
    # Nothing plays until an admin takes the speakers over.
    read_speakers(client)
    assert queue(client)["playing"] is None

    sign_in(client, *ADMIN)
    client.post("/api/playback/play").raise_for_status()
    body = queue(client)
    assert body["playing"]["track"]["title"] == "Song 1"
    assert titles(body) == ["Song 2"]

    # Half a minute from the end, the next request goes to the speakers and is locked in.
    speakers.track_position = 175
    read_speakers(client)
    body = queue(client)
    assert body["next"]["track"]["title"] == "Song 2"
    assert body["waiting"] == []
    assert len(speakers.queue) == 2
    assert vote(client, body["next"], 1).status_code == 409

    # The speakers move on.
    speakers.song_ends()
    read_speakers(client)
    body = queue(client)
    assert body["playing"]["track"]["title"] == "Song 2"
    assert body["next"] is None
    assert body["activity"][0]["text"] == "Now playing Song 2, requested by User"

    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        assert db.execute("SELECT count(*) FROM plays").fetchone() == (2,)


def test_a_request_starts_straight_away_when_the_music_had_run_out(client, speakers) -> None:
    sign_in(client, *ADMIN)
    request(client, "fm1")
    client.post("/api/playback/play").raise_for_status()
    client.post("/api/playback/skip").raise_for_status()
    assert client.get("/api/playback").json()["status"] == "idle"

    request(client, "fm2")
    assert queue(client)["playing"]["track"]["title"] == "Song 2"
    assert client.get("/api/playback").json()["status"] == "playing"


def test_skip_lines_up_the_next_request_first(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    request(client, "fm1")
    request(client, "fm2")
    client.post("/api/playback/play").raise_for_status()
    client.post("/api/playback/skip").raise_for_status()
    body = queue(client)
    assert body["playing"]["track"]["title"] == "Song 2"
    assert client.get("/api/playback").json()["status"] == "playing"


def test_previous_goes_back_and_the_song_it_left_is_next_again(client, speakers) -> None:
    sign_in(client, *ADMIN)
    request(client, "fm1")
    request(client, "fm2")
    client.post("/api/playback/play").raise_for_status()
    client.post("/api/playback/skip").raise_for_status()  # Song 2 playing, just started

    client.post("/api/playback/previous").raise_for_status()
    assert speakers.position == 1
    body = queue(client)
    assert body["playing"] is None  # Song 1 already left the queue when it was skipped
    assert body["next"]["track"]["title"] == "Song 2"

    speakers.song_ends()
    read_speakers(client)
    assert queue(client)["playing"]["track"]["title"] == "Song 2"


def test_previous_well_into_a_song_starts_it_again(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    request(client, "fm1")
    request(client, "fm2")
    client.post("/api/playback/play").raise_for_status()
    client.post("/api/playback/skip").raise_for_status()
    speakers.track_position = 60
    read_speakers(client)

    client.post("/api/playback/previous").raise_for_status()
    assert (speakers.position, speakers.track_position) == (2, 0)
    assert queue(client)["playing"]["track"]["title"] == "Song 2"


def test_a_refused_previous_leaves_the_queue_as_it_was(client, speakers, monkeypatch) -> None:
    sign_in(client, *ADMIN)
    request(client, "fm1")
    request(client, "fm2")
    client.post("/api/playback/play").raise_for_status()
    client.post("/api/playback/skip").raise_for_status()

    def refuse(position: int) -> None:
        raise SpeakersRefused("The speakers wouldn't do that (Illegal seek target).")

    monkeypatch.setattr(speakers, "play_position", refuse)
    assert client.post("/api/playback/previous").status_code == 409
    body = queue(client)
    assert body["playing"]["track"]["title"] == "Song 2"
    assert body["next"] is None


def test_no_going_back_over_a_song_already_lined_up(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    for name in ("fm1", "fm2", "fm3"):
        request(client, name)
    client.post("/api/playback/play").raise_for_status()
    client.post("/api/playback/skip").raise_for_status()
    assert client.get("/api/playback").json()["previous"] == "back"

    # A very short song: Song 3 is lined up while Song 2 has barely started.
    speakers.track_position = 175
    read_speakers(client)
    speakers.track_position = 2
    read_speakers(client)
    assert client.get("/api/playback").json()["previous"] is None
    response = client.post("/api/playback/previous")
    assert response.status_code == 409
    assert "already lined up" in response.json()["detail"]
    assert speakers.position == 2

    # Further in, Previous starts the song again, which leaves the queue as it is.
    speakers.track_position = 60
    read_speakers(client)
    client.post("/api/playback/previous").raise_for_status()
    assert (speakers.position, speakers.track_position) == (2, 0)
    assert queue(client)["next"]["track"]["title"] == "Song 3"


def test_recently_played_songs_are_flagged_but_allowed(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    request(client, "fm1")
    request(client, "fm2")
    client.post("/api/playback/play").raise_for_status()
    client.post("/api/playback/skip").raise_for_status()  # Song 1 done, Song 2 playing

    found = client.get("/api/search", params={"q": "song 1"}).json()["tracks"]
    assert found[0]["played_at"] is not None
    assert request(client, "fm1").status_code == 201
    assert entry_for(client, "Song 1")["played_at"] is not None


@pytest.mark.parametrize("state", ["next", "playing"])
def test_requests_on_their_way_cant_be_removed(client: TestClient, speakers, state) -> None:
    sign_in(client, *ADMIN)
    request(client, "fm1")
    request(client, "fm2")
    client.post("/api/playback/play").raise_for_status()
    speakers.track_position = 190
    read_speakers(client)
    entry = queue(client)[state]
    response = client.delete(f"/api/queue/{entry['id']}")
    assert response.status_code == 409


def test_stop_then_play_carries_on_with_the_same_song(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    request(client, "fm1")
    request(client, "fm2")
    client.post("/api/playback/play").raise_for_status()
    client.post("/api/playback/stop").raise_for_status()
    assert queue(client)["playing"]["track"]["title"] == "Song 1"

    client.post("/api/playback/play").raise_for_status()
    assert queue(client)["playing"]["track"]["title"] == "Song 1"
    assert len(speakers.took_over) == 1  # resumed where it was, not started over
