"""The talk on a talk station (see talk.md): the link before each song, as the queue lines it up.

A link runs as long as the station's talk ratio says (talk.link_seconds), in segments of about
two minutes. Each is written (script.py), voiced so its DJs talk over each other (mixing.py), and
handed to the announcer as soon as it's ready, so it goes into the Sonos queue just before the
song while the one before it plays: the first in the 90 seconds the song is lined up ahead
(queue.LEAD_SECONDS), the rest while the talk plays. Once the song has started, or a segment
can't be written or voiced, the link ends there and the songs carry on.

A show is planned (talk.py) when the station comes on, or when its show opens in a line-up: the
whole show then, an hour at a time outside a line-up. The plan, the show's notes and what was
said lately are kept in the source's dj_memory, so a restart doesn't lose them. A show in a
line-up that has used up its plan plays songs until it ends."""

import asyncio
import logging
import random
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
from guildfm.playlists import current_source
from guildfm.prefs import get_pref
from guildfm.queue import in_state
from guildfm.script import SAID_KEPT, Moment, Turn, write_segment
from guildfm.speech import SpeechClient, SpeechError, is_eleven
from guildfm.talk import (
    SEGMENT_SECONDS,
    Host,
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


def lengths(ratio: int) -> list[int]:
    """How long each segment of a link runs, in seconds, at `ratio` percent talk."""
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


class TalkShow:
    def __init__(
        self,
        sessionmaker,
        announcer: Announcer,
        ai: AIClient,
        speech: SpeechClient,
        awareness: Awareness,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        rng: random.Random | None = None,
    ) -> None:
        self._sessions = sessionmaker
        self._announcer = announcer
        self._ai = ai
        self._speech = speech
        self._awareness = awareness
        self._clock = clock
        self.rng = rng or random.Random()  # deals the moves and rolls the dice
        self._tasks: set[asyncio.Task] = set()

    async def close(self) -> None:
        """Stop talking, before the database closes."""
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def settle(self) -> None:
        """Wait for links being made. For tests."""
        await asyncio.gather(*self._tasks)

    async def lined_up(self, entry_id: int, key: str, opens: int | None = None) -> None:
        """A song was lined up on the speakers: on a talk station, talk before it. Making the
        talk takes a while, so it happens in the background."""
        task = asyncio.create_task(self._safely(entry_id, key, opens))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _safely(self, entry_id: int, key: str, opens: int | None) -> None:
        try:
            await self.link(entry_id, key, opens)
        except (AIError, SpeechError) as error:
            log.warning("The talk show couldn't say anything this time: %s", error)
        except Exception:
            log.exception("The talk show failed")

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
            playing = await in_state(db, EntryState.PLAYING)
            zone = ZoneInfo(await get_pref(db, "timezone"))
            location = await get_pref(db, "weather_location")
            now = self._clock().astimezone(zone)
            show = Show.of(station)
            guests = await _guests(db, station)
            memory: dict[str, Any] = dict(source.dj_memory or {})
            # When the show ends: from the line-up, or as it was when the show opened.
            until = opens if opens is not None else _slot_end(source, station.id, now)
            if until is None and opens is None:
                until = memory.get("until")
            before = _song(playing) if playing else None
            up_next = _up_next(entry, station)
            requester, announcing = entry.requester, station.announce_requests
            named = (
                requester.display_name
                if requester and announcing and requester.announce_requests
                else None
            )
            thumbs_down = len(source.downvotes.get(entry.track_id, []))
            remarks = (
                *await history(db, entry, announcing, named),
                *await votes(db, entry, playing, thumbs_down, announcing),
            )

        if opens is not None or "plan" not in memory:
            memory = await self._plan(show, location, now, until, memory, guests, False)
        elif until is None and memory["segment"] >= memory["count"]:
            memory = await self._plan(show, location, now, until, memory, guests, True)
        elif until is not None and memory["segment"] >= memory["count"]:
            return []  # the show's plan is used up: songs until it ends
        await self._remember(show.station_id, memory)

        async with self._sessions() as db:
            station = await db.get(Station, show.station_id)
            found = await material(db, self._awareness, station, location, now) if station else {}

        segments = lengths(show.ratio)
        moves = list(memory.get("moves", []))
        move = deal_move(self.rng, show.hosts, bool(guests), moves)
        memory["moves"] = [*moves, move][-MOVES_REMEMBERED:]
        plan = memory["plan"]
        happening = plan.get("happening")
        handed: list[Spoken] = []
        for index, seconds in enumerate(segments):
            if not self._announcer.still_to_come(key):
                break  # the song has started
            number = memory["segment"] + 1
            last = until is not None and number >= memory["count"]
            ends_link = last or index == len(segments) - 1
            guest = None
            if guests and (
                (index == 0 and move == "the guest")
                or (happening and happening["kind"] == "a surprise guest"
                    and happening["starts"] == number)
            ):  # fmt: skip
                guest = self.rng.choice(guests)
            moment = Moment(
                number=number,
                count=memory["count"],
                clock=clock_line(now),
                first=number == 1 and not memory.get("continuing"),
                last=last,
                ends_link=ends_link,
                before=before if index == 0 else None,
                up_next=up_next if ends_link else None,
                move=move if index == 0 else None,
                skipped=memory.pop("skipped", None) if index == 0 else None,
                until=clock(until) if until is not None else None,
                guest=guest[0].described() if guest else None,
                remarks=remarks if ends_link else (),
            )
            hosts, voices = show.hosts, show.voices
            if guest:
                hosts, voices = [*hosts, guest[0]], voices | {guest[0].name: guest[1]}
            said = [[Turn(*turn) for turn in segment] for segment in memory.get("said", [])]
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
                    break
                clip = await voice_segment(self._speech, turns, voices, self.rng)
            except (AIError, SpeechError) as error:
                log.warning("Segment %d of %s couldn't be made: %s", number, show.name, error)
                break
            script = "\n".join(f"{turn.speaker}: {turn.text}" for turn in turns)
            spoken = Spoken(
                script, clip, None, AnnounceMode.AFTER, dj=True, for_key=key, title=show.title
            )
            self._announcer.say(spoken)
            handed.append(spoken)
            kept = [[[turn.speaker, turn.text] for turn in turns]]
            memory.update(
                segment=number,
                notes=notes or memory.get("notes", ""),
                said=[*memory.get("said", []), *kept][-SAID_KEPT:],
            )
            await self._remember(show.station_id, memory)
            log.info(
                "%s: segment %d of %d, %d turns, %.0f seconds",
                show.name,
                number,
                memory["count"],
                len(turns),
                clip.seconds,
            )
            if last:
                break
        return handed

    async def _plan(
        self,
        show: Show,
        location: str,
        now: datetime,
        until: int | None,
        memory: dict[str, Any],
        guests: list[tuple[Host, str]],
        continuing: bool,
    ) -> dict[str, Any]:
        """A new plan for the show, or for its next hour outside a line-up (`continuing`), and
        the station's log with its running bits."""
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
