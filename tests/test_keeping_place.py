"""GuildFM keeps its own place on the speakers: a song that won't play is skipped, speakers that
won't start any songs are waited for, stopped speakers going back to the start of their queue
don't take GuildFM with them, and the speakers' queue stays short."""

from fastapi.testclient import TestClient

from guildfm.announcements import STUCK_LINE
from guildfm.playback import FAILED_START_SECONDS, KEEP_PLAYED
from guildfm.queue import WAITING_READINGS
from guildfm.speech import without_tags
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


def test_a_second_try_goes_by_the_speakers_own_queue(client: TestClient, speakers, caplog) -> None:
    started(client, speakers, "fm1", "fm2", "fm3")
    song_change(client, speakers)  # Song 2 on, Song 1 has played
    line_up_next(client, speakers)  # Song 3 lined up
    # Something takes Song 1 off the speakers behind GuildFM's back, so its copy of their
    # queue has one more song in it than they have.
    speakers.remove(1)
    speakers.next_song_fails()
    for _ in range(3):
        read_speakers(client)
    assert (speakers.queue[speakers.position - 1].key, speakers.transport) == (
        key("fm3"),
        "PLAYING",
    )
    assert playing(client) == "Song 3"
    assert "out of step" in caplog.text


def test_a_song_the_speakers_wont_try_again_is_skipped_at_once(
    client: TestClient, speakers
) -> None:
    started(client, speakers, "fm1", "fm2", "fm3")
    line_up_next(client, speakers)
    speakers.wont_seek = key("fm2")
    speakers.next_song_fails()
    for _ in range(3):
        read_speakers(client)
    assert playing(client) == "Song 3"
    assert speakers.transport == "PLAYING"
    assert key("fm2") not in keys(speakers)


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


def history(client: TestClient) -> list[str]:
    return [play["track"]["title"] for play in client.get("/api/history").json()["plays"]]


def activity(client: TestClient) -> list[str]:
    return [line["text"] for line in queue(client)["activity"]]


def test_while_the_speakers_wont_start_songs_guildfm_waits_on_one(client, speakers) -> None:
    started(client, speakers, "fm1", "fm2", "fm3", "fm4", "fm5")
    line_up_next(client, speakers)  # Song 2 lined up
    # Spotify can't be reached from the speakers: each song stops a few seconds in.
    speakers.starts_fail = True
    speakers.song_ends()
    for _ in range(40):
        read_speakers(client)
    # Songs 2 and 3 each had a second try and were let go. With Song 4 the third different
    # song in a row, it's the speakers, so GuildFM holds on to Song 4 instead of going on.
    assert queue(client)["next"]["track"]["title"] == "Song 4"
    assert [entry["track"]["title"] for entry in queue(client)["waiting"]] == ["Song 5"]
    assert client.get("/api/playback").json()["cant_start"] is True
    assert "The speakers won't start any songs, so GuildFM is waiting for them" in activity(client)
    # None of them played, so none is in the history.
    assert history(client) == ["Song 1"]

    tries = len(speakers.played)
    for _ in range(3 * WAITING_READINGS):
        read_speakers(client)
    assert queue(client)["next"]["track"]["title"] == "Song 4"
    # Said once, not again on every try.
    waiting = "The speakers won't start any songs, so GuildFM is waiting for them"
    assert activity(client).count(waiting) == 1
    assert history(client) == ["Song 1"]

    speakers.starts_fail = False
    for _ in range(WAITING_READINGS + 1):
        read_speakers(client)
    assert playing(client) == "Song 4"
    assert speakers.transport == "PLAYING"
    speakers.track_position = FAILED_START_SECONDS
    read_speakers(client)
    assert client.get("/api/playback").json()["cant_start"] is False
    assert history(client) == ["Song 4", "Song 1"]
    assert tries == len(speakers.played)  # nothing played to the end meanwhile


def test_one_song_that_wont_start_isnt_the_speakers(client, speakers) -> None:
    started(client, speakers, "fm1", "fm2", "fm3")
    line_up_next(client, speakers)  # Song 2 lined up
    speakers.starts_fail = True
    speakers.song_ends()
    for _ in range(9):
        read_speakers(client)
    speakers.starts_fail = False  # Song 3 plays
    read_speakers(client)
    read_speakers(client)
    assert playing(client) == "Song 3"
    assert "Song 2 wouldn't play, so it was skipped" in activity(client)
    assert client.get("/api/playback").json()["cant_start"] is False
    assert history(client) == ["Song 3", "Song 1"]


def test_skipping_the_last_song_isnt_a_song_that_wont_start(client, speakers) -> None:
    started(client, speakers, "fm1")
    client.post("/api/playback/skip").raise_for_status()
    for _ in range(10):
        read_speakers(client)
    assert speakers.transport == "STOPPED"
    assert history(client) == ["Song 1"]


def test_songs_the_speakers_lost_come_out_of_guildfms_copy(client, speakers, caplog) -> None:
    started(client, speakers, "fm1", "fm2", "fm3")
    song_change(client, speakers)  # Song 2 on
    line_up_next(client, speakers)  # Song 3 lined up
    speakers.play_position(1)  # someone picks Song 1 again in the Sonos app
    read_speakers(client)
    # Song 2, now after the current song, goes from the speakers behind GuildFM's back.
    speakers.remove(2)
    line_up_next(client, speakers)
    # GuildFM goes by the speakers' own queue: Song 3 stays, nothing is refused.
    assert keys(speakers) == [key("fm1"), key("fm3")]
    assert "out of step" in caplog.text
    assert "Couldn't take a stray song" not in caplog.text
    assert "Took" not in caplog.text


def test_guildfm_says_once_that_the_speakers_wont_start_songs(client, speakers, openai) -> None:
    async def nap(seconds: float) -> None:
        pass

    client.app.state.announcer.sleep = nap

    def a_while(readings: int) -> None:
        for _ in range(readings):
            read_speakers(client)
            client.portal.call(client.app.state.announcer.tick)

    started(client, speakers, *(f"fm{n}" for n in range(1, 9)))
    line_up_next(client, speakers)  # Song 2 lined up
    speakers.starts_fail = True
    speakers.song_ends()
    a_while(40 + 2 * WAITING_READINGS)
    assert client.get("/api/playback").json()["cant_start"] is True
    # Once, in every room, while the speakers are stopped, in the announcement voice. The audio
    # tag is for ElevenLabs voices; an OpenAI voice goes by the instructions.
    assert [(body["input"], body["voice"]) for body in openai.requests] == [
        (without_tags(STUCK_LINE), "cedar")
    ]
    assert "embarrassed" in openai.requests[0]["instructions"]
    assert len(speakers.clips) == len(speakers.rooms)
    assert {clip.music for clip in speakers.clips} == {"STOPPED"}
    recent = client.get("/api/announcements").json()["recent"]
    assert [line["text"] for line in recent] == [STUCK_LINE]

    # Playing again, then stuck again soon after: not said a second time within the hour.
    speakers.starts_fail = False
    a_while(WAITING_READINGS + 1)
    speakers.track_position = FAILED_START_SECONDS
    a_while(1)
    assert client.get("/api/playback").json()["cant_start"] is False
    line_up_next(client, speakers)
    speakers.starts_fail = True
    speakers.song_ends()
    a_while(40)
    assert client.get("/api/playback").json()["cant_start"] is True
    assert len(openai.requests) == 1
    assert len(speakers.clips) == len(speakers.rooms)
