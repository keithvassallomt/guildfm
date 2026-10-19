"""GuildFM keeps its own place on the speakers: a song that won't play is skipped, stopped
speakers going back to the start of their queue don't take GuildFM with them, and the speakers'
queue stays short."""

from fastapi.testclient import TestClient

from guildfm.playback import KEEP_PLAYED
from tests.fakes import FakeSpeakers, spotify_id
from tests.helpers import ADMIN, read_speakers, sign_in


def request(client: TestClient, *names: str) -> None:
    for name in names:
        client.post("/api/queue", json={"track_id": spotify_id(name)}).raise_for_status()


def queue(client: TestClient) -> dict:
    return client.get("/api/queue").json()


def playing(client: TestClient) -> str | None:
    entry = queue(client)["playing"]
    return entry and entry["track"]["title"]


def line_up_next(client: TestClient, speakers: FakeSpeakers) -> None:
    speakers.track_position = 190
    read_speakers(client)


def song_change(client: TestClient, speakers: FakeSpeakers) -> None:
    line_up_next(client, speakers)
    speakers.song_ends()
    read_speakers(client)


def keys(speakers: FakeSpeakers) -> list[str]:
    return [item.key for item in speakers.queue]


def key(name: str) -> str:
    return f"x-sonos-spotify:spotify%3atrack%3a{spotify_id(name)}"


def started(client: TestClient, speakers: FakeSpeakers, *names: str) -> None:
    sign_in(client, *ADMIN)
    request(client, *names)
    client.post("/api/playback/play").raise_for_status()


def test_a_song_that_doesnt_start_gets_a_second_try(client: TestClient, speakers) -> None:
    started(client, speakers, "fm1", "fm2", "fm3")
    line_up_next(client, speakers)
    speakers.next_song_fails()
    read_speakers(client)
    read_speakers(client)
    assert speakers.transport == "STOPPED"  # a moment's grace
    read_speakers(client)
    assert (speakers.queue[speakers.position - 1].key, speakers.transport) == (
        key("fm2"),
        "PLAYING",
    )
    assert playing(client) == "Song 2"


def test_a_lined_up_song_that_wont_play_is_skipped(client: TestClient, speakers) -> None:
    started(client, speakers, "fm1", "fm2", "fm3")
    line_up_next(client, speakers)
    assert queue(client)["next"]["track"]["title"] == "Song 2"
    speakers.wont_start = key("fm2")

    speakers.next_song_fails()
    for _ in range(6):
        read_speakers(client)
    assert playing(client) == "Song 3"
    assert speakers.transport == "PLAYING"
    assert key("fm2") not in keys(speakers)
    activity = [line["text"] for line in queue(client)["activity"]]
    assert "Song 2 wouldn't play, so it was skipped" in activity


def test_play_carries_on_from_guildfms_place_not_the_start(client: TestClient, speakers) -> None:
    started(client, speakers, "fm1", "fm2", "fm3")
    song_change(client, speakers)  # Song 2 on, Song 1 has played
    line_up_next(client, speakers)  # Song 3 lined up
    speakers.next_song_fails()  # stopped, gone back to Song 1
    read_speakers(client)
    client.post("/api/playback/play").raise_for_status()
    assert speakers.queue[speakers.position - 1].key == key("fm3")


def test_the_speakers_queue_stays_short(client: TestClient, speakers) -> None:
    started(client, speakers, *(f"fm{n}" for n in range(1, 8)))
    for _ in range(6):
        song_change(client, speakers)
    assert playing(client) == "Song 7"
    # A few that have played, for Previous, then the one on now.
    assert keys(speakers) == [key(f"fm{n}") for n in range(7 - KEEP_PLAYED, 8)]
    speakers.track_position = 2
    read_speakers(client)
    client.post("/api/playback/previous").raise_for_status()
    assert speakers.queue[speakers.position - 1].key == key("fm6")


def test_songs_the_speakers_went_back_to_come_off(client: TestClient, speakers) -> None:
    started(client, speakers, "fm1", "fm2", "fm3")
    song_change(client, speakers)  # Song 2 on
    line_up_next(client, speakers)  # Song 3 lined up
    speakers.play_position(1)  # someone picks Song 1 again in the Sonos app
    read_speakers(client)
    line_up_next(client, speakers)
    # Song 2 had played: off it comes, so Song 3 is next again.
    assert keys(speakers) == [key("fm1"), key("fm3")]
