from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from guildfm.announcements import Spoken, next_time, upcoming
from guildfm.models import Announcement, AnnounceMode, Repeat
from guildfm.prefs import DEFAULTS
from guildfm.speech import mp3_seconds
from tests.fakes import FakeElevenLabs, FakeOpenAI, FakeSpeakers, mp3, spotify_id
from tests.helpers import ADMIN, read_speakers, sign_in

LONDON = ZoneInfo("Europe/London")
HOURS = DEFAULTS["schedule"]  # weekdays, 08:00 to 18:00
KITCHEN = {"uid": "RINCON_KITCHEN", "name": "Kitchen"}
ARC = {"uid": "RINCON_ARC", "name": "Downstairs"}


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """A time in October 2026, in London. Day 12 is a Monday."""
    return datetime(2026, 10, day, hour, minute, tzinfo=LONDON)


def rule(**fields) -> Announcement:
    defaults = {
        "start_date": date(2026, 10, 13),
        "at": "12:30",
        "repeat": Repeat.ONCE,
        "days": [],
        "ends_on": None,
    }
    return Announcement(**{**defaults, **fields})


# When announcements play


def test_a_one_off_plays_once() -> None:
    once = rule()
    assert next_time(once, at(13, 9)) == at(13, 12, 30)
    assert next_time(once, at(13, 12, 30)) is None


def test_daily_until_the_end_date() -> None:
    daily = rule(repeat=Repeat.DAILY, ends_on=date(2026, 10, 15))
    assert next_time(daily, at(12, 9)) == at(13, 12, 30)  # not before it starts
    assert next_time(daily, at(13, 12, 30)) == at(14, 12, 30)
    assert next_time(daily, at(15, 12, 30)) is None  # the 15th was the last day


def test_weekdays_skip_the_weekend() -> None:
    weekdays = rule(repeat=Repeat.WEEKDAYS)
    assert next_time(weekdays, at(16, 13)) == at(19, 12, 30)  # Friday afternoon to Monday


def test_chosen_days() -> None:
    days = rule(repeat=Repeat.DAYS, days=["tue", "thu"])
    assert next_time(days, at(13, 13)) == at(15, 12, 30)
    assert next_time(days, at(15, 13)) == at(20, 12, 30)


def test_hourly_at_the_same_minutes_past() -> None:
    hourly = rule(repeat=Repeat.HOURLY, at="09:15")
    assert next_time(hourly, at(13, 8)) == at(13, 9, 15)
    assert next_time(hourly, at(13, 9, 15)) == at(13, 10, 15)
    assert next_time(hourly, at(13, 10, 40)) == at(13, 11, 15)


def test_repeating_ones_keep_to_playback_hours() -> None:
    hourly = rule(repeat=Repeat.HOURLY, at="09:15")
    assert upcoming(hourly, at(13, 17, 20), HOURS) == at(14, 8, 15)
    daily = rule(repeat=Repeat.DAILY)
    assert upcoming(daily, at(16, 13), HOURS) == at(19, 12, 30)  # not the weekend
    # A one-off says when it's due even outside them, so the screen can warn about it.
    assert upcoming(rule(at="19:00"), at(13, 9), HOURS) == at(13, 19, 0)


def test_mp3_length_is_counted_from_its_frames() -> None:
    assert mp3_seconds(mp3(3.0)) == pytest.approx(3.0, abs=0.03)
    assert mp3_seconds(b"not an mp3") == 0


# Helpers for the app


@pytest.fixture
def naps(client: TestClient) -> list[tuple[float, bool]]:
    """Each time the announcer waited for a clip, and whether it said it was announcing then.
    Nothing actually waits."""
    waited: list[tuple[float, bool]] = []
    playback = client.app.state.playback

    async def nap(seconds: float) -> None:
        waited.append((seconds, playback.announcing))

    client.app.state.announcer.sleep = nap
    return waited


def tick(client: TestClient) -> None:
    client.portal.call(client.app.state.announcer.tick)


def playing(client: TestClient, speakers: FakeSpeakers, songs: int = 2) -> None:
    """GuildFM playing Song 1, with Song 2 lined up after it."""
    sign_in(client, *ADMIN)
    for number in range(1, songs + 1):
        client.post("/api/queue", json={"track_id": spotify_id(f"fm{number}")}).raise_for_status()
    client.post("/api/playback/play").raise_for_status()
    speakers.track_position = 190
    read_speakers(client)


def near_the_end(client: TestClient, speakers: FakeSpeakers) -> None:
    speakers.track_position = 198  # of 200
    read_speakers(client)


def scheduled(client: TestClient, **fields) -> dict:
    body = {
        "text": "Lunch is ready in the kitchen.",
        "mode": "after",
        "start_date": "2026-10-13",
        "at": "10:30",
        **fields,
    }
    response = client.post("/api/announcements", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def recent(client: TestClient) -> list[dict]:
    return client.get("/api/announcements").json()["recent"]


# Who can announce


def test_only_admins_make_announcements(client: TestClient, people) -> None:
    sign_in(client, *people["curator"])
    assert client.get("/api/announcements").status_code == 403
    assert client.post("/api/announcements/preview", json={"text": "Hi"}).status_code == 403
    response = client.post("/api/announcements/now", json={"text": "Hi", "mode": "over"})
    assert response.status_code == 403


# Previews


def test_preview_reads_it_out_for_the_browser(client: TestClient, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    response = client.post("/api/announcements/preview", json={"text": "Testing, testing."})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content.startswith(b"ID3")
    assert openai.requests[0]["voice"] == "cedar"  # the announcement voice from settings
    assert openai.requests[0]["model"] == "gpt-4o-mini-tts"
    assert "announcement" in openai.requests[0]["instructions"]

    # The same words in the same voice come from the saved copy.
    client.post("/api/announcements/preview", json={"text": "Testing, testing."})
    assert len(openai.requests) == 1
    client.post("/api/announcements/preview", json={"text": "Testing, testing.", "voice": "marin"})
    assert [r["voice"] for r in openai.requests] == ["cedar", "marin"]


def test_openai_problems_are_explained(client: TestClient, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    openai.status = 401
    response = client.post("/api/announcements/preview", json={"text": "Hello"})
    assert response.status_code == 502
    assert "OPENAI_API_KEY" in response.json()["detail"]
    response = client.post(
        "/api/announcements",
        json={"text": "Hi", "mode": "over", "start_date": "2026-10-13", "at": "12:00"},
    )
    assert response.status_code == 502
    assert client.get("/api/announcements").json()["scheduled"] == []


# Now


def test_nothing_plays_while_guildfm_is_stopped(client: TestClient, speakers, openai) -> None:
    sign_in(client, *ADMIN)
    response = client.post("/api/announcements/now", json={"text": "Hello", "mode": "over"})
    assert response.status_code == 409
    assert "stopped" in response.json()["detail"]
    assert openai.requests == []  # not even read out


def test_now_over_the_music_in_every_room(client: TestClient, speakers, naps) -> None:
    playing(client, speakers)
    speakers.tv_turns_on()
    client.portal.call(client.app.state.playback.poll, True)  # rooms are read on a full poll
    response = client.post(
        "/api/announcements/now", json={"text": "Fire drill at ten.", "mode": "over"}
    )
    assert response.json() == {"waits": False}
    tick(client)

    # Each room at its own volume, except the Arc, which is on the TV.
    assert {(c.room, c.volume, c.music) for c in speakers.clips} == {
        ("RINCON_LOUNGE", 20, "PLAYING"),
        ("RINCON_KITCHEN", 19, "PLAYING"),
    }
    # Both rooms wait at the same starting line, so they play it in step.
    first, second = speakers.clips
    assert first.start is second.start and first.start.parties == 2
    assert speakers.clips[0].url.startswith("http://127.0.0.1:8000/media/speech/")
    assert client.get(speakers.clips[0].url.removeprefix("http://127.0.0.1:8000")).content
    assert naps == [(pytest.approx(3.5, abs=0.05), True)]  # the clip, while announcing
    assert client.get("/api/playback").json()["announcing"] is False
    assert recent(client)[0] | {"id": 0, "played_at": ""} == {
        "id": 0,
        "text": "Fire drill at ten.",
        "rooms": None,
        "played_at": "",
        "problem": None,
    }


def test_chosen_rooms_only(client: TestClient, speakers, naps) -> None:
    playing(client, speakers)
    client.post(
        "/api/announcements/now",
        json={"text": "Kitchen's open.", "mode": "over", "rooms": [KITCHEN, ARC]},
    )
    tick(client)
    assert {clip.room for clip in speakers.clips} == {"RINCON_KITCHEN", "RINCON_ARC"}
    assert recent(client)[0]["rooms"] == ["Kitchen", "Downstairs"]


def test_a_room_that_refuses_doesnt_stop_the_others(client: TestClient, speakers, naps) -> None:
    playing(client, speakers)
    speakers.refusing_clips = {"RINCON_KITCHEN"}
    client.post("/api/announcements/now", json={"text": "Hi", "mode": "over"})
    tick(client)
    assert {clip.room for clip in speakers.clips} == {"RINCON_LOUNGE", "RINCON_ARC"}
    assert recent(client)[0]["problem"] is None


def test_between_songs_in_every_room(client: TestClient, speakers: FakeSpeakers, naps) -> None:
    playing(client, speakers)
    response = client.post("/api/announcements/now", json={"text": "Lunch is ready."})
    assert response.json() == {"waits": True}  # after the current song unless asked

    tick(client)
    # Into the Sonos queue straight after Song 1, so the rooms play it in step. The music plays
    # on meanwhile.
    uris = [item.uri for item in speakers.queue]
    assert "/media/speech/" in uris[1] and spotify_id("fm2") in uris[2]
    assert speakers.clips == [] and speakers.transport == "PLAYING"
    assert recent(client)[0]["problem"] is None

    speakers.song_ends()
    read_speakers(client)
    assert client.get("/api/playback").json()["announcing"] is True
    speakers.song_ends()
    read_speakers(client)
    assert client.get("/api/queue").json()["playing"]["track"]["title"] == "Song 2"


def test_on_port_80_clip_addresses_leave_the_port_out(start, settings, speakers) -> None:
    settings.port = 80  # the office machine's, so people open http://guildfm.local
    with start() as client:
        playing(client, speakers)
        client.post("/api/announcements/now", json={"text": "Lunch is ready."})
        tick(client)
        uri = speakers.queue[1].uri
        assert uri.startswith("http://127.0.0.1/media/speech/")
        assert client.get(uri.removeprefix("http://127.0.0.1")).content


def test_a_song_lined_up_later_goes_after_it(client: TestClient, speakers, naps) -> None:
    playing(client, speakers, songs=1)
    client.post("/api/announcements/now", json={"text": "Lunch is ready."})
    tick(client)
    client.post("/api/queue", json={"track_id": spotify_id("fm2")}).raise_for_status()
    read_speakers(client)  # Song 2 is lined up
    uris = [item.uri for item in speakers.queue]
    assert "/media/speech/" in uris[1] and spotify_id("fm2") in uris[2]


def test_an_announcement_goes_ahead_of_the_dj(client: TestClient, speakers, naps) -> None:
    playing(client, speakers)
    announcer = client.app.state.announcer
    line = client.portal.call(announcer.speak, "Coming up, Song 2.")
    (song_2,) = client.app.state.playback.upcoming_keys
    spoken = Spoken("Coming up, Song 2.", line, None, AnnounceMode.AFTER, dj=True, for_key=song_2)
    announcer.say(spoken)
    tick(client)  # the DJ's line goes in first
    client.post("/api/announcements/now", json={"text": "Lunch is ready."})
    tick(client)
    uris = [item.uri for item in speakers.queue]
    assert "/media/speech/" in uris[1] and line.path.name not in uris[1]
    assert line.path.name in uris[2] and spotify_id("fm2") in uris[3]


def test_between_songs_in_chosen_rooms(client: TestClient, speakers: FakeSpeakers, naps) -> None:
    playing(client, speakers)
    body = {"text": "Lunch is ready.", "mode": "after", "rooms": [KITCHEN]}
    response = client.post("/api/announcements/now", json=body)
    assert response.json() == {"waits": True}

    tick(client)  # ten seconds of the song left: it waits
    assert speakers.clips == []
    assert not any("/media/" in item.uri for item in speakers.queue)

    near_the_end(client, speakers)
    tick(client)
    # The music paused for it, then the next song started from the top.
    assert {clip.music for clip in speakers.clips} == {"PAUSED_PLAYBACK"}
    assert (speakers.position, speakers.track_position, speakers.transport) == (2, 0, "PLAYING")
    assert naps[0][0] == pytest.approx(2 - 1.2, abs=0.1)  # paused just before the end
    queue = client.get("/api/queue").json()
    assert queue["playing"]["track"]["title"] == "Song 2"


def test_between_songs_when_nothing_follows(client: TestClient, speakers, naps) -> None:
    playing(client, speakers, songs=1)
    client.post("/api/announcements/now", json={"text": "Lunch is ready.", "mode": "after"})
    near_the_end(client, speakers)
    tick(client)
    assert len(speakers.clips) == 3
    # The last second or so of the song plays out afterwards.
    assert (speakers.position, speakers.transport) == (1, "PLAYING")


def test_paused_music_doesnt_hold_an_announcement_up(client: TestClient, speakers, naps) -> None:
    playing(client, speakers)
    client.post("/api/playback/pause").raise_for_status()
    response = client.post("/api/announcements/now", json={"text": "Hi", "mode": "after"})
    assert response.json() == {"waits": False}
    tick(client)
    assert len(speakers.clips) == 3
    assert speakers.transport == "PAUSED_PLAYBACK"  # and the music stays paused


def test_stop_cancels_one_waiting_for_the_song_to_end(client: TestClient, speakers, naps) -> None:
    playing(client, speakers)
    client.post("/api/announcements/now", json={"text": "Hi", "mode": "after"})
    client.post("/api/playback/stop").raise_for_status()
    tick(client)
    assert speakers.clips == []
    assert recent(client)[0]["problem"] == "GuildFM was stopped"


def test_announcements_go_before_the_dj(client: TestClient, speakers, naps) -> None:
    playing(client, speakers)
    announcer = client.app.state.announcer
    line = client.portal.call(announcer.speak, "Coming up, Fleetwood Mac.")
    (song_2,) = client.app.state.playback.upcoming_keys
    spoken = Spoken("Coming up, Song 2.", line, None, AnnounceMode.AFTER, dj=True, for_key=song_2)
    announcer.say(spoken)
    client.post("/api/announcements/now", json={"text": "Fire drill.", "mode": "over"})
    queued = lambda: any(line.path.name in item.uri for item in speakers.queue)  # noqa: E731

    tick(client)
    assert speakers.clips and not queued()
    tick(client)
    assert queued()  # between the songs, from the Sonos queue
    # The DJ's lines don't go in the announcements log.
    assert [entry["text"] for entry in recent(client)] == ["Fire drill."]


def test_if_elevenlabs_fails_openai_reads_it_out(
    client: TestClient, speakers, naps, openai: FakeOpenAI, elevenlabs: FakeElevenLabs
) -> None:
    playing(client, speakers)
    voice = {"announcement_voice": "elevenlabs:guildbert01"}
    client.patch("/api/settings", json=voice).raise_for_status()
    elevenlabs.status, elevenlabs.detail = 401, {"status": "quota_exceeded"}
    response = client.post("/api/announcements/now", json={"text": "Fire drill.", "mode": "over"})
    assert response.status_code == 200
    tick(client)
    assert len(speakers.clips) == 3
    assert [r["voice"] for r in openai.requests] == ["cedar"]
    # A preview still says what's wrong, so the voice can be put right.
    response = client.post("/api/announcements/preview", json={"text": "Hi"})
    assert response.status_code == 502
    assert "out of credits" in response.json()["detail"]


# Scheduled


def test_scheduling_reads_it_out_ahead(client: TestClient, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    made = scheduled(client, repeat="weekdays", rooms=[KITCHEN])
    assert len(openai.requests) == 1
    assert made["next_at"] == "2026-10-13T10:30:00+01:00"
    assert made["in_hours"] is True
    assert made["rooms"] == [KITCHEN]
    assert client.get("/api/announcements").json()["scheduled"][0]["id"] == made["id"]


def test_schedules_have_to_make_sense(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    base = {"text": "Hi", "mode": "over", "start_date": "2026-10-13", "at": "10:30"}
    cases = [
        ({"repeat": "days", "days": []}, "Pick at least one day."),
        ({"repeat": "daily", "ends_on": "2026-10-12"}, "It can't end before it starts."),
        ({"text": "   "}, None),
        ({"at": "25:00"}, None),
    ]
    for change, message in cases:
        response = client.post("/api/announcements", json={**base, **change})
        assert response.status_code == 422, change
        if message:
            assert message in response.text


def test_recurring_announcement_in_two_rooms_between_songs(
    client: TestClient, speakers: FakeSpeakers, clock, naps
) -> None:
    """Stage 9's "done when": it plays in the two chosen rooms between songs, every day."""
    playing(client, speakers)
    made = scheduled(client, repeat="daily", rooms=[KITCHEN, ARC], mode="after")

    clock.now = datetime(2026, 10, 13, 9, 30, tzinfo=UTC)  # 10:30 in London
    tick(client)
    assert speakers.clips == []  # waiting for the song to end
    near_the_end(client, speakers)
    tick(client)
    assert {(c.room, c.music) for c in speakers.clips} == {
        ("RINCON_KITCHEN", "PAUSED_PLAYBACK"),
        ("RINCON_ARC", "PAUSED_PLAYBACK"),
    }
    assert speakers.transport == "PLAYING"

    # Not again today.
    clock.now = datetime(2026, 10, 13, 9, 45, tzinfo=UTC)
    client.app.state.announcer.refresh()
    tick(client)
    assert len(speakers.clips) == 2
    listed = client.get("/api/announcements").json()["scheduled"]
    assert listed[0]["next_at"] == "2026-10-14T10:30:00+01:00"
    assert listed[0]["id"] == made["id"]


def test_a_scheduled_one_doesnt_play_while_guildfm_is_stopped(
    client: TestClient, speakers, clock, naps
) -> None:
    sign_in(client, *ADMIN)
    scheduled(client, repeat="daily")
    clock.now = datetime(2026, 10, 13, 9, 30, tzinfo=UTC)
    tick(client)
    assert speakers.clips == []
    assert recent(client)[0]["problem"] == "GuildFM was stopped"
    assert len(client.get("/api/announcements").json()["scheduled"]) == 1  # still on for tomorrow


def test_one_offs_go_once_theyve_played(client: TestClient, speakers, clock, naps) -> None:
    playing(client, speakers)
    scheduled(client, mode="over")
    clock.now = datetime(2026, 10, 13, 9, 30, tzinfo=UTC)
    tick(client)
    assert len(speakers.clips) == 3
    assert client.get("/api/announcements").json()["scheduled"] == []
    assert recent(client)[0]["problem"] is None


def test_outside_playback_hours(client: TestClient, speakers, clock, naps) -> None:
    playing(client, speakers)
    scheduled(client, text="Repeating", repeat="daily", at="19:00")
    once = scheduled(client, text="Once", at="19:00")
    assert once["in_hours"] is False

    clock.now = datetime(2026, 10, 13, 18, 0, tzinfo=UTC)  # 19:00 in London
    tick(client)
    assert speakers.clips == []
    # A repeating one keeps to playback hours quietly; a one-off says it missed.
    assert [(e["text"], e["problem"]) for e in recent(client)] == [
        ("Once", "Outside playback hours")
    ]


def test_switched_off_ones_dont_play(client: TestClient, speakers, clock, naps) -> None:
    playing(client, speakers)
    made = scheduled(client, repeat="daily", mode="over")
    client.patch(f"/api/announcements/{made['id']}", json={"active": False}).raise_for_status()

    clock.now = datetime(2026, 10, 13, 9, 30, tzinfo=UTC)
    tick(client)
    assert speakers.clips == []

    # Back on later: today's time has gone, so it waits for tomorrow.
    clock.now = datetime(2026, 10, 13, 9, 32, tzinfo=UTC)
    back = client.patch(f"/api/announcements/{made['id']}", json={"active": True}).json()
    tick(client)
    assert speakers.clips == []
    assert back["next_at"] == "2026-10-14T10:30:00+01:00"


def test_play_a_scheduled_one_now(client: TestClient, speakers, naps) -> None:
    playing(client, speakers)
    made = scheduled(client, repeat="daily", rooms=[KITCHEN])
    response = client.post(f"/api/announcements/{made['id']}/play")
    assert response.json() == {"waits": False}
    tick(client)
    assert [(c.room, c.music) for c in speakers.clips] == [("RINCON_KITCHEN", "PLAYING")]


def test_editing_and_deleting(client: TestClient, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    made = scheduled(client)
    edited = client.put(
        f"/api/announcements/{made['id']}",
        json={
            "text": "Lunch is late today.",
            "mode": "over",
            "start_date": "2026-10-14",
            "at": "13:00",
            "repeat": "days",
            "days": ["thu", "tue", "thu"],
        },
    ).json()
    assert edited["text"] == "Lunch is late today."
    assert edited["days"] == ["tue", "thu"]
    assert edited["next_at"] == "2026-10-15T13:00:00+01:00"
    assert openai.requests[-1]["input"] == "Lunch is late today."

    assert client.delete(f"/api/announcements/{made['id']}").status_code == 204
    assert client.get(f"/api/announcements/{made['id']}").status_code == 404
