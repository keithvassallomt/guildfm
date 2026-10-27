import pytest
from fastapi.testclient import TestClient

from tests.fakes import FakeOpenAI, FakeSpeakers, spotify_id
from tests.helpers import ADMIN, read_speakers, sign_in

FLEETWOOD = [
    {"title": f"Song {n}", "artist": "Fleetwood Mac", "note": f"Note {n}"} for n in range(1, 13)
]


@pytest.fixture(autouse=True)
def no_waiting(client: TestClient) -> None:
    """Clips play instantly here."""

    async def nap(seconds: float) -> None:
        pass

    client.app.state.announcer.sleep = nap


def on_air(client: TestClient, openai: FakeOpenAI, **fields) -> dict:
    """A station with a DJ, on and playing its first song."""
    openai.picks = FLEETWOOD
    body = {
        "name": "Lunchtime Grooves",
        "description": "Upbeat soul.",
        "dj": True,
        "dj_name": "Della",
        "personality": "Warm northern host.",
        "voice": "ash",
        **fields,
    }
    station = client.post("/api/stations", json=body).json()
    client.post(f"/api/stations/{station['id']}/play").raise_for_status()
    client.portal.call(client.app.state.radio.settle)
    client.post("/api/playback/play").raise_for_status()
    return station


def line_up_next(client: TestClient, speakers: FakeSpeakers) -> None:
    """Nearly the end: the next song goes to the speakers and the DJ has its say."""
    speakers.track_position = 190
    read_speakers(client)
    client.portal.call(client.app.state.dj.settle)


def next_song(client: TestClient, speakers: FakeSpeakers) -> None:
    line_up_next(client, speakers)
    speakers.song_ends()
    read_speakers(client)


def tick(client: TestClient) -> None:
    client.portal.call(client.app.state.announcer.tick)


def lines(openai: FakeOpenAI) -> list[str]:
    return [body["input"] for body in openai.asked_for("dj_line")]


def test_the_dj_talks_when_the_station_comes_on_then_every_few_songs(client, openai, speakers):
    sign_in(client, *ADMIN)
    on_air(client, openai, talk_every=2)
    line_up_next(client, speakers)
    assert len(lines(openai)) == 1
    prompt = lines(openai)[0]
    assert 'Just played: "Song 1" by Fleetwood Mac.' in prompt
    assert 'Up next: "Song 2" by Fleetwood Mac. Why it was picked: Note 2' in prompt
    instructions = openai.asked_for("dj_line")[0]["instructions"]
    assert "Della" in instructions and "Warm northern host." in instructions

    speakers.song_ends()
    read_speakers(client)
    next_song(client, speakers)  # Song 3: one song since it talked
    assert len(lines(openai)) == 1
    line_up_next(client, speakers)  # Song 4: two
    assert len(lines(openai)) == 2


def test_the_dj_talks_again_when_the_station_comes_back_on(client, openai, speakers) -> None:
    sign_in(client, *ADMIN)
    station = on_air(client, openai, talk_every=3)
    line_up_next(client, speakers)
    assert len(lines(openai)) == 1
    speakers.song_ends()
    read_speakers(client)
    client.delete("/api/source").raise_for_status()
    client.post(f"/api/stations/{station['id']}/play").raise_for_status()
    client.portal.call(client.app.state.radio.settle)
    line_up_next(client, speakers)
    assert len(lines(openai)) == 2


def test_the_weather_is_only_now_and_then_even_on_the_first_line(client, openai, speakers):
    sign_in(client, *ADMIN)
    on_air(client, openai, global_awareness=True)
    line_up_next(client, speakers)
    assert "Bring up the weather, the time or the news only now and then" in lines(openai)[0]


def test_between_songs(client: TestClient, openai: FakeOpenAI, speakers) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai)
    openai.line = {"script": "That was Song 1. Here's Song 2."}
    line_up_next(client, speakers)
    voiced = openai.requests[-1]
    assert (voiced["voice"], voiced["input"]) == ("ash", "That was Song 1. Here's Song 2.")
    assert "Speak as Della" in voiced["instructions"]

    # Into the Sonos queue just before Song 2, so every room plays it in step, with no pause.
    tick(client)
    song_1, line, song_2 = speakers.queue
    assert "/media/speech/" in line.uri
    assert "<dc:title>Della</dc:title>" in line.metadata
    speakers.song_ends()
    read_speakers(client)
    assert client.get("/api/playback").json()["dj_talking"] is True
    speakers.song_ends()
    read_speakers(client)
    # Once it has played, it comes back out, so Previous goes back to Song 1.
    assert speakers.queue == [song_1, song_2]
    assert (speakers.position, speakers.transport) == (2, "PLAYING")
    assert client.get("/api/playback").json()["dj_talking"] is False
    assert client.get("/api/queue").json()["playing"]["track"]["title"] == "Song 2"
    assert speakers.clips == []
    # The DJ isn't an announcement, so it stays out of the announcements log.
    assert client.get("/api/announcements").json()["recent"] == []


def test_speakers_that_stop_at_the_end_of_a_line_go_straight_on(client, openai, speakers) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai)
    openai.line = {"script": "That was Song 1. Here's Song 2."}
    line_up_next(client, speakers)
    tick(client)
    speakers.song_ends()  # the DJ talks
    read_speakers(client)
    # As the office speakers often do, they stop at the end of the line and go back to the start
    # of their queue instead of going on to Song 2. GuildFM starts it on the next reading.
    speakers.next_song_fails()
    read_speakers(client)
    assert speakers.transport == "PLAYING"
    assert client.get("/api/queue").json()["playing"]["track"]["title"] == "Song 2"


def test_between_songs_with_a_pause_if_the_queue_wont_take_it(client, openai, speakers) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai)
    openai.line = {"script": "That was Song 1. Here's Song 2."}
    speakers.queue_refuses_clips = True
    line_up_next(client, speakers)
    tick(client)
    assert {clip.music for clip in speakers.clips} == {"PAUSED_PLAYBACK"}
    assert (speakers.position, speakers.transport) == (2, "PLAYING")


def test_a_line_between_songs_comes_off_with_its_song(client, openai, speakers) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai)
    openai.line = {"script": "That was Song 1. Here's Song 2."}
    line_up_next(client, speakers)
    tick(client)
    assert len(speakers.queue) == 3
    client.delete("/api/source").raise_for_status()  # Song 2 comes back off the speakers
    assert len(speakers.queue) == 1


def test_a_line_too_late_for_the_queue_is_let_go(client: TestClient, openai, speakers) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai)
    line_up_next(client, speakers)
    speakers.track_position = 198  # two seconds left: too late to go in the queue
    read_speakers(client)
    tick(client)
    speakers.song_ends()
    read_speakers(client)
    tick(client)
    # Never over the music, which would echo from room to room.
    assert speakers.clips == []
    assert not any("/media/" in item.uri for item in speakers.queue)
    assert speakers.position == 2


def test_a_line_for_a_song_that_doesnt_come_is_dropped(client, openai, speakers) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai)
    openai.line = {"script": "Here's Song 2."}
    line_up_next(client, speakers)
    client.delete("/api/source").raise_for_status()  # Song 2 comes back off the speakers
    speakers.song_ends()
    read_speakers(client)
    tick(client)
    assert speakers.clips == []


def test_no_crossfade_into_or_out_of_the_dj(client: TestClient, openai, speakers) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai, crossfade=True)
    line_up_next(client, speakers)
    assert speakers.crossfade is True  # Song 2 is lined up, to fade into
    tick(client)  # the DJ's line goes in ahead of it
    assert speakers.crossfade is False
    speakers.song_ends()  # the DJ talks
    read_speakers(client)
    assert speakers.crossfade is False
    speakers.song_ends()  # Song 2, which fades into the next song again
    read_speakers(client)
    assert speakers.crossfade is True


def test_request_shout_outs(client: TestClient, people, openai: FakeOpenAI, speakers) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai, talk_every=10)
    next_song(client, speakers)  # the DJ says hello with Song 2

    sign_in(client, *people["user"])
    client.patch("/api/me", json={"announce_requests": False}).raise_for_status()
    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()
    next_song(client, speakers)
    # The user opted out, and it isn't time to talk anyway.
    assert len(lines(openai)) == 1

    sign_in(client, *people["curator"])
    client.post("/api/queue", json={"track_id": spotify_id("gyow")}).raise_for_status()
    line_up_next(client, speakers)
    assert 'Up next: "Go Your Own Way" by Fleetwood Mac. Curator requested it' in lines(openai)[-1]


def test_requests_arent_mentioned_when_the_station_says_not_to(client, people, openai, speakers):
    sign_in(client, *ADMIN)
    on_air(client, openai, announce_requests=False)
    sign_in(client, *people["user"])
    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()
    line_up_next(client, speakers)
    assert "User" not in lines(openai)[0]
    assert "request" not in lines(openai)[0]


def test_the_dj_knows_the_time_and_with_global_awareness_the_weather(client, openai, speakers):
    sign_in(client, *ADMIN)
    on_air(client, openai, global_awareness=True)
    line_up_next(client, speakers)
    assert "It's Tuesday 13 October, 10:00, morning." in lines(openai)[0]
    assert "The weather in Carlisle, Cumbria, UK right now: light rain" in lines(openai)[0]


def test_without_global_awareness_just_the_time(client, openai, speakers) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai)
    line_up_next(client, speakers)
    assert "It's Tuesday 13 October, 10:00, morning." in lines(openai)[0]
    assert "weather" not in lines(openai)[0]


def test_no_dj_no_talking(client: TestClient, openai: FakeOpenAI, speakers) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai, dj=False)
    line_up_next(client, speakers)
    assert lines(openai) == []


def test_when_the_ai_fails_the_dj_stays_quiet(client, openai: FakeOpenAI, speakers) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai)
    openai.down = True
    next_song(client, speakers)
    tick(client)
    assert speakers.clips == []
    assert client.get("/api/queue").json()["playing"]["track"]["title"] == "Song 2"


def test_the_dj_knows_about_repeat_requests(client: TestClient, people, openai, speakers) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai, talk_every=10)
    sign_in(client, *people["user"])
    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()
    next_song(client, speakers)  # Dreams, for User
    next_song(client, speakers)  # Song 2, from the station
    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()  # again
    sign_in(client, *people["curator"])
    entry = client.get("/api/queue").json()["waiting"][0]
    client.post(f"/api/queue/{entry['id']}/vote", json={"value": 1}).raise_for_status()
    line_up_next(client, speakers)

    prompt = lines(openai)[-1]
    assert (
        "This song has played once in the last week, most recently a moment ago, "
        "requested by User." in prompt
    )
    assert "Fleetwood Mac has played 3 times in the last week." in prompt
    assert "Votes on this request: 1 up, 0 down." in prompt
    assert (
        "Requests from User that played in the last week: 1, 1 of them by Fleetwood Mac." in prompt
    )
    assert "teasing" in openai.asked_for("dj_line")[-1]["instructions"]


def test_people_who_opted_out_arent_named_in_the_history(client, people, openai, speakers):
    sign_in(client, *ADMIN)
    on_air(client, openai, talk_every=10)
    sign_in(client, *people["user"])
    client.patch("/api/me", json={"announce_requests": False}).raise_for_status()
    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()
    next_song(client, speakers)  # Dreams, for User
    next_song(client, speakers)  # Song 2, from the station
    sign_in(client, *people["curator"])
    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()
    line_up_next(client, speakers)
    prompt = lines(openai)[-1]
    assert "requested by someone." in prompt
    assert "User" not in prompt
