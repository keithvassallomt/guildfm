"""Talk stations on air: planning the show, and the talk before each song."""

import random
import re
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from guildfm.lineups import minute_of
from guildfm.models import DJProfile, EntryState, Play, SourceState, Station, Track
from guildfm.prefs import DEFAULTS
from guildfm.queue import in_state
from tests import test_lineups as lineups
from tests.fakes import FakeElevenLabs, FakeOpenAI, FakeSpeakers, spotify_id
from tests.helpers import ADMIN, read_speakers, sign_in

FLEETWOOD = [
    {"title": f"Song {n}", "artist": "Fleetwood Mac", "note": f"Note {n}"} for n in range(1, 13)
]


@pytest.fixture(autouse=True)
def steady(client: TestClient) -> None:
    """Clips play instantly here, and the dice always roll the same."""

    async def nap(seconds: float) -> None:
        pass

    client.app.state.announcer.sleep = nap
    client.app.state.talk.rng = random.Random(4)


async def _station(sessionmaker, ratio: int, hosts: int = 2) -> int:
    async with sessionmaker() as db:
        guildbert = DJProfile(
            name="Guildbert",
            personality="Cheeky.",
            voice="elevenlabs:guildbert01",
            pet_peeves="Songs that fade out.",
            created_at=0,
        )
        debbie = DJProfile(
            name="Debbie", personality="Bubbly.", voice="elevenlabs:aurora02", created_at=0
        )
        station = Station(
            name="The Lunch Break",
            description="Feel-good soul.",
            talk_station=True,
            talk_ratio=ratio,
            script_prompt="Light chat about the [weather].",
            dynamic="Debbie can't let Guildbert finish a story.",
            created_at=0,
        )
        station.set_hosts([guildbert, debbie][:hosts])
        db.add(station)
        await db.commit()
        return station.id


def on_air(client: TestClient, openai: FakeOpenAI, ratio: int = 40, hosts: int = 2) -> int:
    """A talk station, on and playing its first song."""
    openai.picks = FLEETWOOD
    station = client.portal.call(_station, client.app.state.sessionmaker, ratio, hosts)
    client.post(f"/api/stations/{station}/play").raise_for_status()
    client.portal.call(client.app.state.radio.settle)
    client.post("/api/playback/play").raise_for_status()
    return station


def line_up_next(client: TestClient, speakers: FakeSpeakers) -> None:
    """Nearly the end: the next song goes to the speakers and the talk is made."""
    speakers.track_position = 190
    read_speakers(client)
    client.portal.call(client.app.state.talk.settle)
    client.portal.call(client.app.state.dj.settle)


def next_song(client: TestClient, speakers: FakeSpeakers) -> None:
    """The song and the talk after it play out, and the next song starts."""
    client.portal.call(client.app.state.announcer.tick)
    speakers.song_ends()
    read_speakers(client)
    while "/media/" in speakers.queue[speakers.position - 1].uri:
        speakers.song_ends()
        read_speakers(client)


def segments(openai: FakeOpenAI) -> list[str]:
    return [body["input"] for body in openai.asked_for("talk_segment")]


async def _memory(sessionmaker) -> dict:
    async with sessionmaker() as db:
        source = await db.get(SourceState, 1)
        return dict(source.dj_memory or {})


async def _log(sessionmaker, station_id: int) -> list[dict]:
    async with sessionmaker() as db:
        return list((await db.get(Station, station_id)).talk_log)


def test_a_talk_station_talks_before_each_song(
    client: TestClient,
    openai: FakeOpenAI,
    elevenlabs: FakeElevenLabs,
    speakers: FakeSpeakers,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sign_in(client, *ADMIN)
    station = on_air(client, openai)
    caplog.set_level("INFO", logger="guildfm.talkshow")
    line_up_next(client, speakers)
    # The journal notes what each segment cost, to compare with the slider's estimate.
    assert "The Lunch Break: segment 1 of 12, " in caplog.text
    assert "2 turns, 90 characters, 40 credits; written in" in caplog.text

    # Planned once, outside a line-up an hour at a time: 12 segments of talk at 40%.
    (plan,) = openai.asked_for("show_plan")
    assert "This plans the next 60 minutes of the show: 12 segments." in plan["input"]
    assert "Debbie can't let Guildbert finish a story." in plan["instructions"]
    # At 40%, a link is one segment, about as long as two-fifths of a song and a song.
    (told,) = segments(openai)
    assert "It opens the show: welcome everyone" in told
    assert "A song has just finished" not in told  # it played before the show
    assert not re.search(r"segment \d", told, re.IGNORECASE)  # never said, so never told
    assert 'End by bringing in the next one: "Song 2" by Fleetwood Mac' in told
    assert "Write about 2380 characters of speech, about 140 seconds." in told
    assert "[weather]\nRight now in Carlisle, Cumbria, UK: light rain" in told
    # The DJ leaves it to them.
    assert openai.asked_for("dj_line") == []

    # Each turn voiced in its DJ's voice, then mixed into one clip, just before Song 2.
    assert [r["voice"] for r in elevenlabs.requests] == ["guildbert01", "aurora02"]
    client.portal.call(client.app.state.announcer.tick)
    song_1, talk, song_2 = speakers.queue
    assert "/media/speech/" in talk.uri
    assert "<dc:title>Guildbert and Debbie</dc:title>" in talk.metadata

    memory = client.portal.call(_memory, client.app.state.sessionmaker)
    assert (memory["segment"], memory["count"]) == (1, 12)
    assert memory["notes"] == "Debbie has won the biscuit."
    bits = client.portal.call(_log, client.app.state.sessionmaker, station)
    assert bits and all(bit["move"] in ("the bet", "the score", "the challenge") for bit in bits)

    # The next link carries on from the first, with no new plan.
    next_song(client, speakers)
    line_up_next(client, speakers)
    assert len(openai.asked_for("show_plan")) == 1
    told = segments(openai)[1]
    assert "It opens the show" not in told
    assert 'A song has just finished: "Song 2" by Fleetwood Mac.' in told
    assert "The show's notes so far: Debbie has won the biscuit." in told
    assert "Guildbert: Right, before you start, I have a theory." in told
    # What today's DJ knows about the songs, the talk show knows too.
    assert "About the songs, to bring up now and then" in told


def test_the_journal_says_what_the_edit_fixed(
    client: TestClient,
    openai: FakeOpenAI,
    speakers: FakeSpeakers,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai)
    openai.edit = {"problems": ["Turn 2 answers nothing."], "turns": openai.segment["turns"]}
    caplog.set_level("INFO", logger="guildfm.talkshow")
    line_up_next(client, speakers)
    assert "Segment 1, edited: Turn 2 answers nothing." in caplog.text


def test_a_talk_station_is_planned_as_it_comes_on(
    client: TestClient, openai: FakeOpenAI, speakers: FakeSpeakers, clock
) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai)
    client.portal.call(client.app.state.talk.settle)
    # Planned while its first song plays, so its first talk only has to be written and voiced.
    assert len(openai.asked_for("show_plan")) == 1
    assert segments(openai) == []
    line_up_next(client, speakers)
    assert len(openai.asked_for("show_plan")) == 1
    assert "It opens the show" in segments(openai)[0]

    # The next day, yesterday's plan is no good: the show starts afresh.
    clock.now += timedelta(days=1)
    next_song(client, speakers)
    line_up_next(client, speakers)
    assert len(openai.asked_for("show_plan")) == 2
    assert "It opens the show" in segments(openai)[-1]


async def _at_segment(sessionmaker, number: int) -> None:
    async with sessionmaker() as db:
        source = await db.get(SourceState, 1)
        source.dj_memory = {**source.dj_memory, "segment": number}
        await db.commit()


def test_the_next_hour_is_planned_while_this_one_finishes(
    client: TestClient, openai: FakeOpenAI, speakers: FakeSpeakers
) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai)
    line_up_next(client, speakers)
    sessionmaker = client.app.state.sessionmaker
    client.portal.call(_at_segment, sessionmaker, 10)  # of 12

    # Two segments left: the next hour's plan is made while they play...
    next_song(client, speakers)
    line_up_next(client, speakers)
    assert len(openai.asked_for("show_plan")) == 2
    next_song(client, speakers)
    line_up_next(client, speakers)
    assert len(openai.asked_for("show_plan")) == 2

    # ...and the hour after carries on from it, without stopping to plan.
    next_song(client, speakers)
    line_up_next(client, speakers)
    assert len(openai.asked_for("show_plan")) == 2
    memory = client.portal.call(_memory, sessionmaker)
    assert (memory["segment"], memory["continuing"]) == (1, True)
    assert "It opens the show" not in segments(openai)[-1]


def test_a_talk_show_in_a_line_up_is_planned_before_it_opens(
    client: TestClient, openai: FakeOpenAI, speakers: FakeSpeakers, clock
) -> None:
    sign_in(client, *ADMIN)
    openai.picks = FLEETWOOD
    station = client.portal.call(_station, client.app.state.sessionmaker, 40)
    playlist = lineups.make_playlist(client)
    slots = [
        lineups.playlist_slot(playlist, "09:45", "10:15"),
        lineups.show({"id": station}, "10:15", "11:00"),
    ]
    lineup = lineups.make_lineup(client, slots).json()
    lineups.at(clock, 10, 0)
    lineups.put_on(client, lineup)
    client.post("/api/playback/play").raise_for_status()

    # Ten minutes or less before it opens, the show is planned as it'll be at 10:15.
    lineups.at(clock, 10, 6)
    lineups.line_up_next(client, speakers)
    client.portal.call(client.app.state.talk.settle)
    (plan,) = openai.asked_for("show_plan")
    assert "It's Tuesday 13 October, 10:15." in plan["input"]
    assert "The show runs until 11:00: 9 segments of talk." in plan["input"]
    assert segments(openai) == []
    lineups.next_song(client, speakers)

    # As it opens, its first talk uses that plan.
    lineups.at(clock, 10, 14, 55)
    line_up_next(client, speakers)
    assert len(openai.asked_for("show_plan")) == 1
    assert "It opens the show" in segments(openai)[0]


def test_more_talk_is_more_segments_before_the_song(
    client: TestClient, openai: FakeOpenAI, speakers: FakeSpeakers
) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai, ratio=80)
    line_up_next(client, speakers)
    told = segments(openai)
    assert len(told) == 7  # 14 minutes between songs, in 2-minute segments
    assert [n for n, t in enumerate(told) if "It opens the show" in t] == [0]
    # The rest carry straight on, mid-conversation: no song plays between them.
    assert [n for n, t in enumerate(told) if "carries straight on" in t] == [1, 2, 3, 4, 5, 6]
    assert [n for n, t in enumerate(told) if "End by bringing in" in t] == [6]
    client.portal.call(client.app.state.announcer.tick)
    assert len(speakers.queue) == 9
    assert all("/media/speech/" in item.uri for item in speakers.queue[1:8])


async def _lined_up(sessionmaker, queue) -> tuple[int, str]:
    async with sessionmaker() as db:
        entry = await in_state(db, EntryState.NEXT)
        return entry.id, queue.item(entry).key


def test_a_show_in_a_line_up_signs_off_then_plays_songs(
    client: TestClient, openai: FakeOpenAI, speakers: FakeSpeakers, clock
) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai)
    line_up_next(client, speakers)
    talk, state = client.app.state.talk, client.app.state
    # As if the song opened a show in a line-up that ends in five minutes.
    entry_id, key = client.portal.call(_lined_up, state.sessionmaker, state.queue)
    now = clock().astimezone(ZoneInfo(DEFAULTS["timezone"]))
    ends = minute_of(now) + 5
    client.portal.call(talk.link, entry_id, key, ends)
    plan = openai.asked_for("show_plan")[-1]["input"]
    assert "The show runs until" in plan and ": 2 segments of talk." in plan
    assert "It opens the show" in segments(openai)[-1]

    client.portal.call(talk.link, entry_id, key, None)
    assert "It's the show's last segment" in segments(openai)[-1]
    asked = len(segments(openai))
    assert client.portal.call(talk.link, entry_id, key, None) == []  # songs until it ends
    assert len(segments(openai)) == asked


def test_when_voicing_fails_the_songs_carry_on(
    client: TestClient, openai: FakeOpenAI, elevenlabs: FakeElevenLabs, speakers: FakeSpeakers
) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai)
    elevenlabs.status = 500
    line_up_next(client, speakers)
    client.portal.call(client.app.state.announcer.tick)
    assert len(speakers.queue) == 2  # no talk, just the songs
    assert all("/media/" not in item.uri for item in speakers.queue)


def test_one_dj_isnt_a_talk_show(
    client: TestClient, openai: FakeOpenAI, speakers: FakeSpeakers
) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai, hosts=1)
    line_up_next(client, speakers)
    assert openai.asked_for("show_plan") == []
    assert len(openai.asked_for("dj_line")) == 1  # the DJ talks between songs, as ever


def test_the_talk_after_a_skipped_segment_knows_it_wasnt_heard(
    client: TestClient, openai: FakeOpenAI, speakers: FakeSpeakers
) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai)
    line_up_next(client, speakers)
    client.portal.call(client.app.state.announcer.tick)
    speakers.song_ends()
    read_speakers(client)
    assert "/media/speech/" in speakers.queue[speakers.position - 1].uri  # the talk is on

    client.post("/api/playback/skip").raise_for_status()
    read_speakers(client)
    assert "/media/" not in speakers.queue[speakers.position - 1].uri  # Song 2
    line_up_next(client, speakers)
    told = segments(openai)[1]
    assert "Listeners didn't hear the last segment: someone skipped it." in told

    # Told once.
    next_song(client, speakers)
    line_up_next(client, speakers)
    assert "Listeners didn't hear" not in segments(openai)[2]


async def _heard_long_ago(sessionmaker) -> str:
    async with sessionmaker() as db:
        track = Track(
            id=spotify_id("dreams"),
            title="Dreams",
            artists="Fleetwood Mac",
            album="Rumours",
            duration_ms=257000,
            explicit=False,
            art_url=None,
        )
        db.add_all([track, Play(track_id=track.id, played_at=0.0)])
        await db.commit()
        return track.id


def test_all_talk_opens_with_a_song_while_its_first_talk_is_made(
    client: TestClient, openai: FakeOpenAI, speakers: FakeSpeakers
) -> None:
    sign_in(client, *ADMIN)
    sessionmaker = client.app.state.sessionmaker
    dreams = client.portal.call(_heard_long_ago, sessionmaker)
    station = client.portal.call(_station, sessionmaker, 100)
    client.post(f"/api/stations/{station}/play").raise_for_status()
    client.portal.call(client.app.state.talk.settle)
    assert len(openai.asked_for("show_plan")) == 1  # planned as it comes on

    # Play: a song heard before goes on straight away, with no wait for the talk...
    client.post("/api/playback/play").raise_for_status()
    (song,) = speakers.queue
    assert dreams in song.uri
    assert openai.asked_for("picks") == []  # without asking the AI

    # ...and the show opens after it, from the plan made ahead.
    speakers.track_position = 190
    read_all(client)
    client.portal.call(client.app.state.talk.settle)
    assert "/media/speech/" in speakers.queue[-1].uri
    assert "It opens the show" in segments(openai)[0]
    assert len(openai.asked_for("show_plan")) == 1


def read_all(client: TestClient) -> None:
    """A reading of the speakers, as the app does every second: the queue has its go, then the
    talk show, which keeps all talk going."""
    read_speakers(client)
    client.portal.call(client.app.state.talk.keep_talking)


def test_all_talk_talks_on_and_still_plays_requests(
    client: TestClient, openai: FakeOpenAI, speakers: FakeSpeakers
) -> None:
    sign_in(client, *ADMIN)
    station = client.portal.call(_station, client.app.state.sessionmaker, 100)
    client.post(f"/api/stations/{station}/play").raise_for_status()
    client.portal.call(client.app.state.radio.settle)
    assert openai.asked_for("picks") == []  # no songs of its own

    # Play with nothing lined up: the talk starts once its first segment is made.
    client.post("/api/playback/play").raise_for_status()
    client.portal.call(client.app.state.talk.settle)
    read_all(client)
    (talk,) = speakers.queue
    assert "/media/speech/" in talk.uri
    assert client.get("/api/playback").json()["dj_talking"] is True
    told = segments(openai)[0]
    assert "It opens the show" in told
    assert "End by bringing in" not in told

    # Towards its end, the next segment goes on after it, as a song would.
    speakers.track_position = 190
    read_all(client)
    client.portal.call(client.app.state.talk.settle)
    assert len(speakers.queue) == 2
    assert "carries straight on from the last segment" in segments(openai)[1]
    memory = client.portal.call(_memory, client.app.state.sessionmaker)
    assert (memory["segment"], memory["count"]) == (2, 30)  # an hour, all talk

    # A request still plays, brought in by a segment of its own...
    speakers.song_ends()
    read_all(client)
    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()
    speakers.track_position = 190
    read_all(client)
    client.portal.call(client.app.state.talk.settle)
    client.portal.call(client.app.state.announcer.tick)
    told = segments(openai)[2]
    assert 'End by bringing in the next one: "Dreams" by Fleetwood Mac, requested by' in told
    assert "/media/speech/" in speakers.queue[-2].uri
    assert "/media/" not in speakers.queue[-1].uri  # Dreams

    # ...and the talk carries on after it.
    speakers.song_ends()
    read_all(client)
    speakers.song_ends()
    read_all(client)
    speakers.track_position = 190
    read_all(client)
    client.portal.call(client.app.state.talk.settle)
    told = segments(openai)[3]
    assert 'A song has just finished: "Dreams" by Fleetwood Mac.' in told
    assert "/media/speech/" in speakers.queue[-1].uri

    # Only once: the talk after that carries straight on.
    speakers.song_ends()
    read_all(client)
    speakers.track_position = 190
    read_all(client)
    client.portal.call(client.app.state.talk.settle)
    told = segments(openai)[4]
    assert "carries straight on" in told and "Dreams" not in told
