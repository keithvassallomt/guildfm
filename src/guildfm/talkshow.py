"""The talk on a talk station (see talk.md): the link before each song, as the queue lines it up.

A link runs as long as the station's talk ratio says (talk.link_seconds), in segments of about
two minutes. Each is written (script.py), voiced so its DJs talk over each other (mixing.py), and
handed to the announcer as soon as it's ready, so it goes into the Sonos queue just before the
song while the one before it plays: the first in the 90 seconds the song is lined up ahead
(queue.LEAD_SECONDS), the rest while the talk plays. Once the song has started, or a segment
can't be written or voiced, the link ends there and the songs carry on.

At 100% talk the station picks no songs, so there's nothing for the talk to go before. Then,
after each reading of the speakers, the talk show keeps a segment queued after whatever's on,
or starts one if nothing is. Requests still play: a request's link is one segment bringing it
in, and the talk carries on after it.

A show is planned (talk.py) when the station comes on, or when its show opens in a line-up: the
whole show then, an hour at a time outside a line-up. The plan, the show's notes and what was
said lately are kept in the source's dj_memory, so a restart doesn't lose them. A show in a
line-up that has used up its plan plays songs until it ends."""

import asyncio
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.ai import AIClient, AIError
from guildfm.announcements import Announcer, Spoken
from guildfm.awareness import Awareness, clock_line
from guildfm.dj import history, votes
from guildfm.fields import FROM_THE_WEB, material, used
from guildfm.lineups import clock, minute_of, slot_at
from guildfm.mixing import voice_segment
from guildfm.models import (
    AnnounceMode,
    DJProfile,
    EntryState,
    QueueEntry,
    SourceState,
    Station,
)
from guildfm.playback import PlaybackController, Status
from guildfm.playlists import current_source
from guildfm.prefs import get_pref
from guildfm.queue import LEAD_SECONDS, in_state
from guildfm.script import SAID_KEPT, Moment, Turn, write_segment
from guildfm.speech import Clip, SpeechClient, SpeechError, is_eleven
from guildfm.talk import (
    SEGMENT_SECONDS,
    Host,
    all_talk,
    deal_bits,
    deal_move,
    link_seconds,
    logged,
    plan_show,
    roll_happening,
    talks,
)

log = logging.getLogger(__name__)

HOUR = 60  # minutes planned at a time outside a line-up
SHORTEST_SHOW = 10  # minutes planned at least, for a show that's nearly over
MATERIAL_WAIT = 20  # seconds a show's plan waits for its web fields to come in
LONGEST = 30 * 60  # seconds of talk between two songs at most
MOVES_REMEMBERED = 5
MOVE_EVERY = 3  # segments, at 100% talk, where there are no links to deal moves to
SEGMENTS_REMEMBERED = 200  # handed-over segments known by their clip, for skips


def lengths(ratio: int) -> list[int]:
    """How long each segment of a link runs, in seconds, at `ratio` percent talk. At 100%, the
    only songs are requests, and a request's link is one segment bringing it in."""
    if ratio >= 100:
        return [SEGMENT_SECONDS]
    total = min(link_seconds(ratio) or LONGEST, LONGEST)
    count = max(1, round(total / SEGMENT_SECONDS))
    return [round(total / count)] * count


def _listed(names: list[str]) -> str:
    return names[0] if len(names) < 2 else f"{', '.join(names[:-1])} and {names[-1]}"


@dataclass(frozen=True)
class Show:
    """A talk station as its talk needs it, read once per link."""

    station_id: int
    name: str
    hosts: list[Host]
    voices: dict[str, str]  # each DJ's ElevenLabs voice, by name
    dynamic: str
    prompt: str
    ratio: int
    log: list[dict[str, str]]

    @classmethod
    def of(cls, station: Station) -> Show:
        djs = station.hosts
        return cls(
            station.id,
            station.name,
            [Host.of(dj) for dj in djs],
            {dj.name: dj.voice for dj in djs},
            station.dynamic,
            station.script_prompt,
            station.talk_ratio,
            list(station.talk_log),
        )

    @property
    def title(self) -> str:
        """What the Sonos app shows while the talk plays."""
        return _listed([host.name for host in self.hosts])


async def _guests(db: AsyncSession, station: Station) -> list[tuple[Host, str]]:
    """GuildFM's other DJs who could drop in: not on the station, with ElevenLabs voices."""
    own = {dj.id for dj in station.hosts}
    everyone = await db.scalars(select(DJProfile).order_by(DJProfile.id))
    return [(Host.of(dj), dj.voice) for dj in everyone if dj.id not in own and is_eleven(dj.voice)]


def _slot_end(source: SourceState, station_id: int, now: datetime) -> int | None:
    """When the station's show in the line-up that's on ends, if it's on in one now."""
    if source.lineup is None:
        return None
    slot = slot_at(source.lineup, minute_of(now))
    return slot.end if slot and slot.station_id == station_id else None


def _either(told: int | None, stored: int | None) -> int | None:
    """A skip the talk show was told of, or one kept in its memory: both, so neither is told
    to the writer twice."""
    return told if told is not None else stored


def _song(entry: QueueEntry) -> str:
    return f'"{entry.track.title}" by {entry.track.artists}'


def _up_next(entry: QueueEntry, station: Station) -> str:
    """The song a link brings in, and who asked for it, if the station says and they don't
    mind."""
    song = _song(entry)
    requester = entry.requester
    if requester and station.announce_requests and requester.announce_requests:
        return f"{song}, requested by {requester.display_name}: say their name."
    if requester and station.announce_requests:
        return f"{song}, a request."
    return song


@dataclass
class OnAir:
    """A talk station's show as a link, or a stretch of talk at 100%, finds it."""

    show: Show
    guests: list[tuple[Host, str]]  # other DJs who could drop in, with their voices
    memory: dict[str, Any]  # the source's dj_memory: the plan, the notes, what was said
    until: int | None  # the minute the show ends, in a line-up
    location: str
    now: datetime  # in the office's time zone
    before: str | None  # the song that just played


TOGETHER_SECONDS = 30  # "Hear them together" in the station editor


async def together(
    ai: AIClient,
    speech: SpeechClient,
    *,
    station: str,
    hosts: list[Host],
    voices: dict[str, str],
    dynamic: str,
    prompt: str,
    now: datetime,
) -> Clip:
    """A half-minute exchange between DJs, written and voiced the way a talk station's are, for
    the station editor to play, so people can hear how they get on before saving."""
    plan = {
        "segments": ["A quick taste of the show: show how they get on, in a few lines."],
        "bits": [],
        "happening": None,
    }
    moment = Moment(number=1, count=1, clock=clock_line(now))
    turns, _, _ = await write_segment(
        ai,
        station=station,
        hosts=hosts,
        dynamic=dynamic,
        prompt=prompt,
        plan=plan,
        moment=moment,
        material={},
        notes="",
        said=[],
        seconds=TOGETHER_SECONDS,
    )
    if not turns:
        raise AIError("The AI didn't write anything for them this time. Try again.")
    return await voice_segment(speech, turns, voices)


class TalkShow:
    def __init__(
        self,
        sessionmaker,
        announcer: Announcer,
        ai: AIClient,
        speech: SpeechClient,
        awareness: Awareness,
        controller: PlaybackController,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        rng: random.Random | None = None,
    ) -> None:
        self._sessions = sessionmaker
        self._announcer = announcer
        self._ai = ai
        self._speech = speech
        self._awareness = awareness
        self._controller = controller
        self._clock = clock
        self.rng = rng or random.Random()  # deals the moves and rolls the dice
        self._tasks: set[asyncio.Task] = set()
        self._feeding: asyncio.Task | None = None  # the next stretch of talk at 100%
        # The segments handed over lately, by clip ("speech/....mp3"): the station and number.
        self._segments: dict[str, tuple[int, int]] = {}
        # Segments skipped and not yet told to the writer, by station. Also kept in dj_memory
        # for a restart, but a link being made could save over that.
        self._skips: dict[int, int] = {}

    async def close(self) -> None:
        """Stop talking, before the database closes."""
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def settle(self) -> None:
        """Wait for talk being made. For tests."""
        await asyncio.gather(*self._tasks)

    def _start(self, work) -> asyncio.Task:
        task = asyncio.create_task(self._safely(work))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _safely(self, work) -> None:
        try:
            await work
        except (AIError, SpeechError) as error:
            log.warning("The talk show couldn't say anything this time: %s", error)
        except Exception:
            log.exception("The talk show failed")

    async def lined_up(self, entry_id: int, key: str, opens: int | None = None) -> None:
        """A song was lined up on the speakers: on a talk station, talk before it. Making the
        talk takes a while, so it happens in the background."""
        self._start(self.link(entry_id, key, opens))

    async def keep_talking(self) -> None:
        """After each reading of the speakers: at 100% talk, keep a segment queued after
        whatever's on, as a song would be, or start one if nothing's playing."""
        controller = self._controller
        if self._feeding and not self._feeding.done():
            return
        if not controller.in_control or controller.anything_ahead:
            return
        status, left = controller.status, controller.time_left
        if status == Status.PLAYING and (left is None or left > LEAD_SECONDS):
            return
        if status not in (Status.PLAYING, Status.IDLE):
            return
        self._feeding = self._start(self.carry_on(start=status == Status.IDLE))

    async def warm_up(self) -> bool:
        """Play was pressed with nothing to play: on a 100% talk station, make the first talk
        and start it once it's ready, in about half a minute."""
        async with self._sessions() as db:
            source = await current_source(db)
            station = source.station if source and source.station_id else None
            if station is None or not all_talk(station):
                return False
        if not (self._feeding and not self._feeding.done()):
            self._feeding = self._start(self.carry_on(start=True))
        return True

    async def _on_air(
        self,
        db: AsyncSession,
        source: SourceState,
        station: Station,
        opens: int | None,
    ) -> OnAir:
        zone = ZoneInfo(await get_pref(db, "timezone"))
        now = self._clock().astimezone(zone)
        memory: dict[str, Any] = dict(source.dj_memory or {})
        # When the show ends: from the line-up, or as it was when the show opened.
        until = opens if opens is not None else _slot_end(source, station.id, now)
        if until is None and opens is None:
            until = memory.get("until")
        playing = await in_state(db, EntryState.PLAYING)
        return OnAir(
            Show.of(station),
            await _guests(db, station),
            memory,
            until,
            await get_pref(db, "weather_location"),
            now,
            _song(playing) if playing else None,
        )

    async def _planned(self, air: OnAir, opens: int | None) -> bool:
        """Plans the show if it needs it: when it opens, comes on, or an hour's plan outside a
        line-up runs out. False once a line-up's show has used up its plan."""
        memory = air.memory
        if opens is not None or "plan" not in memory:
            air.memory = await self._plan(air, False)
        elif memory["segment"] >= memory["count"]:
            if air.until is not None:
                return False  # songs until the show ends
            air.memory = await self._plan(air, True)
        await self._remember(air.show.station_id, air.memory)
        return True

    async def _material(self, air: OnAir) -> dict[str, str]:
        async with self._sessions() as db:
            station = await db.get(Station, air.show.station_id)
            if station is None:
                return {}
            return await material(db, self._awareness, station, air.location, air.now)

    async def link(self, entry_id: int, key: str, opens: int | None = None) -> list[Spoken]:
        """The talk before the song lined up as `entry_id`, a segment at a time. A song that
        `opens` a line-up's show, which runs until that minute, starts the show. Returns what
        was handed to the announcer."""
        async with self._sessions() as db:
            source = await current_source(db)
            station = source.station if source and source.station_id else None
            entry = await db.get(QueueEntry, entry_id)
            if source is None or station is None or entry is None or not talks(station):
                return []
            air = await self._on_air(db, source, station, opens)
            up_next = _up_next(entry, station)
            requester, announcing = entry.requester, station.announce_requests
            named = (
                requester.display_name
                if requester and announcing and requester.announce_requests
                else None
            )
            playing = await in_state(db, EntryState.PLAYING)
            thumbs_down = len(source.downvotes.get(entry.track_id, []))
            remarks = (
                *await history(db, entry, announcing, named),
                *await votes(db, entry, playing, thumbs_down, announcing),
            )

        if not await self._planned(air, opens):
            return []
        found = await self._material(air)
        segments = lengths(air.show.ratio)
        move = self._deal(air)
        handed: list[Spoken] = []
        for index, seconds in enumerate(segments):
            if not self._announcer.still_to_come(key):
                break  # the song has started
            number = air.memory["segment"] + 1
            last = air.until is not None and number >= air.memory["count"]
            ends_link = last or index == len(segments) - 1
            spoken = await self._segment(
                air,
                found,
                seconds,
                key=key,
                before=air.before if index == 0 else None,
                up_next=up_next if ends_link else None,
                move=move if index == 0 else None,
                remarks=remarks if ends_link else (),
            )
            if spoken is None:
                break
            self._announcer.say(spoken)
            handed.append(spoken)
            if last:
                break
        return handed

    async def carry_on(self, start: bool = False) -> Spoken | None:
        """At 100% talk, the next segment, queued after whatever's on, or started straight away
        with `start`. Returns what was put on the speakers, if anything."""
        async with self._sessions() as db:
            source = await current_source(db)
            station = source.station if source and source.station_id else None
            if source is None or station is None or not all_talk(station):
                return None
            if await in_state(db, EntryState.NEXT):
                return None  # a request is lined up, and its link brings it in
            air = await self._on_air(db, source, station, None)

        if not await self._planned(air, None):
            return None
        found = await self._material(air)
        number = air.memory["segment"] + 1
        move = self._deal(air) if number % MOVE_EVERY == 1 else None
        spoken = await self._segment(
            air, found, SEGMENT_SECONDS, key=None, before=air.before, up_next=None, move=move
        )
        if spoken and not await self._announcer.keep_on(spoken, start):
            return None
        return spoken

    def _deal(self, air: OnAir) -> str:
        """A move for a link, or a stretch of talk at 100%, remembered so it rests."""
        moves = list(air.memory.get("moves", []))
        move = deal_move(self.rng, air.show.hosts, bool(air.guests), moves)
        air.memory["moves"] = [*moves, move][-MOVES_REMEMBERED:]
        return move

    async def _segment(
        self,
        air: OnAir,
        found: dict[str, str],
        seconds: int,
        *,
        key: str | None,
        before: str | None,
        up_next: str | None,
        move: str | None,
        remarks: tuple[str, ...] = (),
    ) -> Spoken | None:
        """The show's next segment, written and voiced, and remembered as said. None if it
        couldn't be made."""
        show, memory = air.show, air.memory
        plan = memory["plan"]
        number = memory["segment"] + 1
        last = air.until is not None and number >= memory["count"]
        happening = plan.get("happening")
        guest = None
        surprise = (
            happening and happening["kind"] == "a surprise guest" and happening["starts"] == number
        )
        if air.guests and (move == "the guest" or surprise):
            guest = self.rng.choice(air.guests)
        moment = Moment(
            number=number,
            count=memory["count"],
            clock=clock_line(air.now),
            first=number == 1 and not memory.get("continuing"),
            last=last,
            ends_link=up_next is not None,
            before=before,
            up_next=up_next,
            move=move,
            skipped=_either(self._skips.pop(show.station_id, None), memory.pop("skipped", None)),
            until=clock(air.until) if air.until is not None else None,
            guest=guest[0].described() if guest else None,
            remarks=remarks,
        )
        hosts, voices = show.hosts, show.voices
        if guest:
            hosts, voices = [*hosts, guest[0]], voices | {guest[0].name: guest[1]}
        said = [[Turn(*turn) for turn in segment] for segment in memory.get("said", [])]
        started, spent = time.monotonic(), self._speech.talk_credits
        try:
            turns, notes, problems = await write_segment(
                self._ai,
                station=show.name,
                hosts=hosts,
                dynamic=show.dynamic,
                prompt=show.prompt,
                plan=plan,
                moment=moment,
                material=found,
                notes=memory.get("notes", ""),
                said=said,
                seconds=seconds,
            )
            if problems:
                log.info("Segment %d's marks taken off: %s", number, " ".join(problems))
            if not turns:
                return None
            written = time.monotonic()
            clip = await voice_segment(self._speech, turns, voices, self.rng)
        except (AIError, SpeechError) as error:
            log.warning("Segment %d of %s couldn't be made: %s", number, show.name, error)
            return None
        self._segments[clip.media_path] = (show.station_id, number)
        while len(self._segments) > SEGMENTS_REMEMBERED:
            self._segments.pop(next(iter(self._segments)))
        kept = [[[turn.speaker, turn.text] for turn in turns]]
        memory.update(
            segment=number,
            notes=notes or memory.get("notes", ""),
            said=[*memory.get("said", []), *kept][-SAID_KEPT:],
        )
        await self._remember(show.station_id, memory)
        # What it cost, to compare with the talk slider's estimate after a day at the office.
        log.info(
            "%s: segment %d of %d, %.0f seconds of talk, %d turns, %d characters, %d credits; "
            "written in %.0f s, voiced in %.0f s",
            show.name,
            number,
            memory["count"],
            clip.seconds,
            len(turns),
            sum(len(turn.text) for turn in turns),
            self._speech.talk_credits - spent,
            written - started,
            time.monotonic() - written,
        )
        script = "\n".join(f"{turn.speaker}: {turn.text}" for turn in turns)
        return Spoken(
            script, clip, None, AnnounceMode.AFTER, dj=True, for_key=key, title=show.title
        )

    async def skipped(self, key: str | None) -> None:
        """Someone pressed Skip while `key` was playing: if it was a segment of talk, the next
        one is told listeners didn't hear it, so it doesn't pay off what it set up."""
        found = next(
            (where for path, where in self._segments.items() if key and key.endswith(f"/{path}")),
            None,
        )
        if found is None:
            return
        station_id, number = found
        self._skips[station_id] = number
        async with self._sessions() as db:
            source = await current_source(db)
            if source and source.station_id == station_id and source.dj_memory:
                source.dj_memory = {**source.dj_memory, "skipped": number}
                await db.commit()
        log.info("Segment %d was skipped", number)

    async def _plan(self, air: OnAir, continuing: bool) -> dict[str, Any]:
        """A new plan for the show, or for its next hour outside a line-up (`continuing`), and
        the station's log with its running bits."""
        show, location, now, until = air.show, air.location, air.now, air.until
        memory, guests = air.memory, air.guests
        minutes = max(SHORTEST_SHOW, until - minute_of(now)) if until is not None else HOUR
        web = [name for name in used(show.prompt) if name in FROM_THE_WEB]
        if web:
            await self._awareness.ready(web, now.date(), MATERIAL_WAIT)
        async with self._sessions() as db:
            station = await db.get(Station, show.station_id)
            found = await material(db, self._awareness, station, location, now) if station else {}
        bits = deal_bits(self.rng, show.log)
        happening = roll_happening(self.rng, bool(guests))
        plan = await plan_show(
            self._ai,
            station=show.name,
            hosts=show.hosts,
            dynamic=show.dynamic,
            prompt=show.prompt,
            material=found,
            starts=now,
            minutes=minutes,
            ratio=show.ratio,
            bits=bits,
            happening=happening,
            log=show.log,
            until=clock(until) if until is not None else None,
        )
        log.info(
            "%s planned: %d segments, %s, %s",
            show.name,
            len(plan["segments"]),
            " and ".join(bits),
            happening or "no happening",
        )
        async with self._sessions() as db:
            station = await db.get(Station, show.station_id)
            if station:
                station.talk_log = logged(station.talk_log, plan, now.date().isoformat())
                await db.commit()
        kept = memory if continuing else {}
        return {
            "plan": plan,
            "count": len(plan["segments"]),
            "segment": 0,
            "continuing": continuing,
            "until": until,
            "notes": kept.get("notes", ""),
            "said": kept.get("said", []),
            "moves": kept.get("moves", []),
        }

    async def _remember(self, station_id: int, memory: dict[str, Any]) -> None:
        """Keep the show's memory on the source, so a restart doesn't lose it. Let go if the
        station went off meanwhile."""
        async with self._sessions() as db:
            source = await current_source(db)
            if source and source.station_id == station_id:
                source.dj_memory = dict(memory)
                await db.commit()
