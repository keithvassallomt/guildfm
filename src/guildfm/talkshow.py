"""The talk on a talk station (see talk.md): the link before each song, as the queue lines it up.

A link runs as long as the station's talk ratio says (talk.link_seconds), in segments of two
minutes at most (talk.segment_lengths). Each is written (script.py), voiced so its DJs talk over
each other (mixing.py), and handed to the announcer as soon as it's ready, so it goes into the
Sonos queue just before the song while the one before it plays: the first in the 90 seconds the
song is lined up ahead (queue.LEAD_SECONDS), the rest while the talk plays. Once the song has
started, or a segment can't be written or voiced, the link ends there and the songs carry on.

At 100% talk the station picks no songs, so there's nothing for the talk to go before. Then,
after each reading of the speakers, the talk show keeps a segment queued after whatever's on,
or starts one if nothing is. Requests still play: a request's link is one segment bringing it
in, and the talk carries on after it.

A show is planned (talk.py) ahead of its first talk, in the background, so that talk only has
to be written and voiced: when the station is put on, ten minutes before its show in a line-up,
and while the last few segments of an hour's plan play outside one. In a line-up the whole show
is planned, outside one an hour at a time. The plan, the show's notes and what was said lately
are kept in the source's dj_memory, so a restart doesn't lose them, and a plan from another day
is planned afresh. A show in a line-up that has used up its plan plays songs until it ends."""

import asyncio
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
from guildfm.script import SAID_KEPT, Moment, Turn, deal_mention, remembered, write_segment
from guildfm.speech import Clip, SpeechClient, SpeechError, is_eleven
from guildfm.talk import (
    SEGMENT_SECONDS,
    Host,
    all_talk,
    deal_bits,
    deal_hooks,
    deal_move,
    does,
    is_feature,
    logged,
    plan_show,
    roll_happening,
    segment_lengths,
    talks,
    told_lately,
    with_hooks,
    with_told,
)

log = logging.getLogger(__name__)

HOUR = 60  # minutes planned at a time outside a line-up
SHORTEST_SHOW = 10  # minutes planned at least, for a show that's nearly over
MATERIAL_WAIT = 20  # seconds a show's plan waits for its web fields to come in
MATERIAL_WAIT_AHEAD = 90  # the same for a line-up's show, planned ten minutes before it opens
AHEAD_KEPT = timedelta(minutes=30)  # how long a plan made ahead is good for
NEXT_HOUR_AHEAD = 2  # segments left in an hour's plan when the next hour's is made
LOOK_EVERY = 30.0  # seconds between checks that a talk station playing has today's plan
MOVES_REMEMBERED = 5
MOVE_EVERY = 3  # segments, at 100% talk, where there are no links to deal moves to
SEGMENTS_REMEMBERED = 200  # handed-over segments known by their clip, for skips


def _day(now: datetime) -> str:
    return now.date().isoformat()


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
    log: list[dict[str, Any]]  # the station's last few shows
    features: list[dict[str, str]]  # its own recurring features, in place of banter moves

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
            list(station.features or []),
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

    @property
    def hosts(self) -> list[Host]:
        """The DJs, with the hooks dealt to the show."""
        return with_hooks(self.show.hosts, (self.memory.get("plan") or {}).get("hooks"))


@dataclass
class Ahead:
    """A show being planned, or planned, before its first talk."""

    until: int | None  # the minute its show ends, in a line-up
    made: datetime
    task: asyncio.Task[dict[str, Any] | None]  # the plan, or None if it couldn't be made


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
    written = await write_segment(
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
        edit=False,  # a quick taste, played while someone waits in the editor
    )
    turns = written.turns
    if not turns:
        raise AIError("The AI didn't write anything for them this time. Try again.")
    return await voice_segment(speech, turns, voices)


DYNAMIC_INSTRUCTIONS = """You write how the DJs on a radio talk show get on with each other, \
for the people setting up the show. Its writers read it before every segment.

From who each DJ is, write three or four plain sentences: what each makes of the other, who \
winds whom up and how, who interrupts whom, and where they side together. Draw on their \
personalities. Leave their pet peeves, soft spots and obsessions as they are: those come up a \
show at a time, and this comes up in every show, so it's about the two of them, not running \
jokes. Warm underneath: they bicker, but they like each other. British English, everyday words, \
no lists, no headings, no dashes, and under 600 characters."""

DYNAMIC = {
    "type": "object",
    "properties": {"dynamic": {"type": "string"}},
    "required": ["dynamic"],
    "additionalProperties": False,
}


async def suggest_dynamic(ai: AIClient, *, station: str, hosts: list[Host], prompt: str) -> str:
    """How `hosts` might get on, written by the AI from who they are, for the station editor's
    "Suggest one". Raises AIError if it can't."""
    parts = [f"The show: {station}." if station else "A new show."]
    if prompt:
        parts.append(f"What it's about: {prompt}")
    parts.append("The DJs:\n" + "\n".join(host.described() for host in hosts))
    answer = await ai.json(DYNAMIC_INSTRUCTIONS, "\n\n".join(parts), "dynamic", DYNAMIC)
    dynamic = str(answer.get("dynamic", "")).strip()
    if not dynamic:
        raise AIError("The AI didn't suggest anything this time. Try again.")
    return dynamic[:1000]


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
        self._ahead: dict[int, Ahead] = {}  # shows planned ahead, by station
        self._looked: float | None = None  # when _look_ahead last looked, on time.monotonic

    async def close(self) -> None:
        """Stop talking, before the database closes."""
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def settle(self) -> None:
        """Wait for talk being made, and shows being planned. For tests."""
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def _start(self, work) -> asyncio.Task:
        return self._track(asyncio.create_task(self._safely(work)))

    def _track(self, task: asyncio.Task) -> asyncio.Task:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def prepare(self, station_id: int, until: int | None = None, starts: int | None = None) -> None:
        """A station is coming on, or its show in a line-up opens soon (at the minute `starts`,
        until the minute `until`): if it's a talk station, plan its show now, in the background,
        so its first talk only has to be written and voiced."""
        ahead = self._ahead.get(station_id)
        if ahead and ahead.until == until and self._clock() - ahead.made < AHEAD_KEPT:
            return  # planned, or being planned
        if ahead:
            ahead.task.cancel()
        task = self._track(asyncio.create_task(self._plan_ahead(station_id, until, starts)))
        self._ahead[station_id] = Ahead(until, self._clock(), task)

    async def _plan_ahead(
        self, station_id: int, until: int | None, starts: int | None
    ) -> dict[str, Any] | None:
        try:
            async with self._sessions() as db:
                station = await db.get(Station, station_id)
                if station is None or not talks(station):
                    return None
                now = self._clock().astimezone(ZoneInfo(await get_pref(db, "timezone")))
                if starts is not None:  # planned as it'll be when the show opens
                    hour, minute = divmod(starts, 60)
                    now = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                location = await get_pref(db, "weather_location")
                air = OnAir(
                    Show.of(station), await _guests(db, station), {}, until, location, now, None
                )
            wait = MATERIAL_WAIT if starts is None else MATERIAL_WAIT_AHEAD
            return await self._plan(air, wait)
        except (AIError, SpeechError) as error:
            log.warning("A talk show couldn't be planned ahead: %s", error)
        except Exception:
            log.exception("Planning a talk show ahead failed")
        return None

    async def _made_ahead(self, air: OnAir) -> dict[str, Any] | None:
        """The plan made ahead for this show, if there's one that's still good, waiting for it
        if it's nearly done."""
        ahead = self._ahead.pop(air.show.station_id, None)
        if ahead is None:
            return None
        if ahead.until != air.until or self._clock() - ahead.made >= AHEAD_KEPT:
            ahead.task.cancel()
            return None
        return await ahead.task

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
        """After each reading of the speakers: a talk station playing gets its show planned if
        it has none, and at 100% talk, a segment is kept queued after whatever's on, as a song
        would be, or one is started if nothing's playing."""
        controller = self._controller
        if controller.in_control:
            await self._look_ahead()
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

    async def _look_ahead(self) -> None:
        """Every so often while a song plays: a talk station on by hand with no plan for today
        gets one now, so its first talk only has to be written and voiced. Coming on plans it
        too, but Play on a station that was already on, the morning's first song and a restart
        don't come on. Line-ups plan their shows before they open."""
        if self._controller.status != Status.PLAYING or self._tasks:
            return  # not playing, or talk is being made, which plans the show if it needs it
        now = time.monotonic()
        if self._looked is not None and now - self._looked < LOOK_EVERY:
            return
        self._looked = now
        async with self._sessions() as db:
            source = await current_source(db)
            station = source.station if source and source.station_id else None
            if station is None or source.lineup_id is not None or not talks(station):
                return
            memory = source.dj_memory or {}
            today = _day(self._clock().astimezone(ZoneInfo(await get_pref(db, "timezone"))))
        if "plan" not in memory or memory.get("day") != today:
            self.prepare(station.id)

    async def warm_up(self) -> bool:
        """Play was pressed with nothing to play, on a 100% talk station with no song heard
        before to open with: make the first talk and start it once it's ready, in under a
        minute with its show planned ahead, or a minute and a half without."""
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
        line-up runs out, using the plan made ahead if there is one. False once a line-up's
        show has used up its plan."""
        memory, station_id = air.memory, air.show.station_id
        if opens is not None or "plan" not in memory or memory.get("day") != _day(air.now):
            continuing = False
        elif memory["segment"] >= memory["count"]:
            if air.until is not None:
                return False  # songs until the show ends
            continuing = True
        else:
            if air.until is None and memory["count"] - memory["segment"] <= NEXT_HOUR_AHEAD:
                self.prepare(station_id)  # the next hour, while this one finishes
            return True
        plan = await self._made_ahead(air) or await self._plan(air, MATERIAL_WAIT)
        kept = memory if continuing else {}
        air.memory = {
            "plan": plan,
            "count": len(plan["segments"]),
            "segment": 0,
            "continuing": continuing,
            "until": air.until,
            "day": _day(air.now),
            "notes": kept.get("notes", ""),
            "said": kept.get("said", []),
            "moves": kept.get("moves", []),
            "heard": kept.get("heard"),
        }
        async with self._sessions() as db:
            station = await db.get(Station, station_id)
            if station:
                station.talk_log = logged(station.talk_log, plan, _day(air.now))
                await db.commit()
        await self._remember(station_id, air.memory)
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
        segments = segment_lengths(air.show.ratio)
        # The song before a show's opening isn't talked about, so it gets no verdict.
        opening = air.memory["segment"] == 0 and not air.memory.get("continuing")
        move = self._deal(air, song=not opening)
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
                straight_on=index > 0,
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
        # A request that played since the last segment, if one did; otherwise the talk runs on.
        heard = air.before if air.before != air.memory.get("heard") else None
        air.memory["heard"] = air.before
        opening = number == 1 and not air.memory.get("continuing")
        song = heard is not None and not opening
        move = self._deal(air, song) if number % MOVE_EVERY == 1 else None
        spoken = await self._segment(
            air,
            found,
            SEGMENT_SECONDS,
            key=None,
            before=heard,
            straight_on=heard is None,
            up_next=None,
            move=move,
        )
        if spoken and not await self._announcer.keep_on(spoken, start):
            return None
        return spoken

    def _deal(self, air: OnAir, song: bool) -> str:
        """A move for a link, or a stretch of talk at 100%, remembered so it rests. `song` is
        whether a song just played, for the talk to be about."""
        moves = list(air.memory.get("moves", []))
        move = deal_move(self.rng, air.hosts, bool(air.guests), moves, song, air.show.features)
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
        straight_on: bool = False,
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
        mention = "name"
        if before and not straight_on:
            mention = deal_mention(self.rng, memory.get("mention"), move)
            memory["mention"] = mention
        moment = Moment(
            number=number,
            count=memory["count"],
            clock=clock_line(air.now),
            first=number == 1 and not memory.get("continuing"),
            last=last,
            ends_link=up_next is not None,
            straight_on=straight_on,
            before=before,
            up_next=up_next,
            move=move,
            does=does(move, show.features) if move else "",
            feature=is_feature(move, show.features),
            mention=mention,
            skipped=_either(self._skips.pop(show.station_id, None), memory.pop("skipped", None)),
            until=clock(air.until) if air.until is not None else None,
            guest=guest[0].described() if guest else None,
            remarks=remarks,
        )
        hosts, voices = air.hosts, show.voices
        if guest:
            hosts, voices = [*hosts, guest[0]], voices | {guest[0].name: guest[1]}
        said = [[Turn(*turn) for turn in segment] for segment in memory.get("said", [])]
        started, spent = time.monotonic(), self._speech.talk_credits
        try:
            segment = await write_segment(
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
                lately=told_lately(show.log, air.now.date()),
            )
            turns, notes = segment.turns, segment.notes
            if segment.fixed:
                log.info("Segment %d, edited: %s", number, " ".join(segment.fixed))
            if segment.marks:
                log.info("Segment %d's marks taken off: %s", number, " ".join(segment.marks))
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
        # With the song that played before it, so those after it know where the music was.
        kept = [[[turn.speaker, turn.text] for turn in remembered(moment, turns)]]
        memory.update(
            segment=number,
            notes=notes or memory.get("notes", ""),
            said=[*memory.get("said", []), *kept][-SAID_KEPT:],
        )
        await self._remember(show.station_id, memory)
        await self._log_told(show.station_id, _day(air.now), segment.told)
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

    async def _plan(self, air: OnAir, wait: float) -> dict[str, Any]:
        """A new plan for the show, or for its next hour outside a line-up, waiting up to `wait`
        seconds for its web fields."""
        show, location, now, until = air.show, air.location, air.now, air.until
        minutes = max(SHORTEST_SHOW, until - minute_of(now)) if until is not None else HOUR
        web = [name for name in used(show.prompt) if name in FROM_THE_WEB]
        if web:
            await self._awareness.ready(web, now.date(), wait)
        async with self._sessions() as db:
            station = await db.get(Station, show.station_id)
            found = await material(db, self._awareness, station, location, now) if station else {}
        bits = deal_bits(self.rng, show.log)
        hooks = deal_hooks(self.rng, show.hosts, show.log)
        happening = roll_happening(self.rng, bool(air.guests), banter=not show.features)
        plan = await plan_show(
            self._ai,
            station=show.name,
            hosts=with_hooks(show.hosts, hooks),
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
            features=show.features,
        )
        plan["hooks"] = hooks
        log.info(
            "%s planned: %d segments, %s, %s; hooks: %s",
            show.name,
            len(plan["segments"]),
            " and ".join(bits),
            happening or "no happening",
            "; ".join(
                f"{name}'s {', '.join(hook.replace('_', ' ') for hook in had)}"
                for name, had in hooks.items()
            )
            or "none",
        )
        return plan

    async def _log_told(self, station_id: int, day: str, items: list[str]) -> None:
        """What a segment told, kept with today's show in the station's log for a week, so no
        show tells it again."""
        if not items:
            return
        async with self._sessions() as db:
            station = await db.get(Station, station_id)
            if station:
                station.talk_log = with_told(station.talk_log, day, items)
                await db.commit()

    async def _remember(self, station_id: int, memory: dict[str, Any]) -> None:
        """Keep the show's memory on the source, so a restart doesn't lose it. Let go if the
        station went off meanwhile."""
        async with self._sessions() as db:
            source = await current_source(db)
            if source and source.station_id == station_id:
                source.dj_memory = dict(memory)
                await db.commit()
