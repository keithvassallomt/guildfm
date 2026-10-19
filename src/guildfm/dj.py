"""The DJ: a voice on an AI station that introduces songs, comments on them and gives shout-outs
for requests, in the station's personality and voice.

GuildFM asks the DJ about each song as it's lined up on the speakers, about half a minute before
the current one ends. The DJ talks every so many songs or minutes, as the station says, and for
every request while announcing requests is on, unless the person who asked opted out. The AI
writes the line, which plays between the songs from the Sonos queue, so every room hears it in
step. It never goes over music: Sonos plays a clip over the music one room at a time, with no way
to start the rooms together, so they echo. Lines go through the announcer, so announcements
always go first.
"""

import asyncio
import logging
import math
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.ai import AIClient, AIError, object_schema
from guildfm.announcements import Announcer, Spoken
from guildfm.awareness import Awareness, clock_line
from guildfm.models import (
    AnnounceMode,
    DJStyle,
    EntryState,
    PickNote,
    Play,
    QueueEntry,
    TalkUnit,
    Track,
)
from guildfm.playlists import current_source
from guildfm.prefs import get_pref
from guildfm.queue import in_state, tallies
from guildfm.speech import SpeechClient, SpeechError, is_eleven

log = logging.getLogger(__name__)

RECENT_LINES = 3  # what the DJ said lately, so it doesn't repeat itself
HISTORY_DAYS = 7  # how far back the DJ looks at what's played and who asked for it

INSTRUCTIONS = (
    "You are {dj}, the DJ on {station}, a radio station playing over the speakers in an office "
    "in the UK. Your personality: {personality}\n\n"
    "Write what you say next. {speech} Never make up facts about a song or an artist; leave "
    "trivia out if you aren't sure of it. Be respectful about sad news. "
    "You can comment on requests and the people who make them: if it suits your personality, "
    "a little good-natured teasing about a repeat request or a guilty pleasure is welcome. Keep "
    "it about the music, and never be mean. {style}"
)
PLAIN = (
    "It's read out by text to speech, so write it the way you'd say it: no stage directions, "
    "sound effects, emoji or hashtags."
)
# For an ElevenLabs voice, which understands audio tags.
TAGGED = (
    "It's read out by an expressive text to speech voice, so write it the way you'd say it. You "
    "can steer how it's said with an audio tag in square brackets before the words it's for, "
    "such as [laughs], [chuckles], [sighs], [excited], [whispers] or [sarcastic]. Use one or two "
    "at most, only where they suit your personality and the moment. No other stage directions, "
    "and no sound effects, emoji or hashtags."
)
STYLES = {
    DJStyle.ANNOUNCE: "Keep it short and simple: what just played, and what's next.",
    DJStyle.COMMENTARY: (
        "Add a little colour: some trivia, the weather or the time of day, or a story about the "
        "song. Keep it brief all the same."
    ),
}
WHERE = "It plays between the songs, before the next one starts: keep it under 25 seconds."
LINE = object_schema(script={"type": "string"})


def _ago(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 2:
        return "a moment ago"
    if minutes < 90:
        return f"{minutes} minutes ago"
    hours = round(minutes / 60)
    return f"{hours} hours ago" if hours < 36 else f"{round(hours / 24)} days ago"


def _listed(items: list[str]) -> str:
    return items[0] if len(items) < 2 else f"{', '.join(items[:-1])} and {items[-1]}"


def _times(count: int) -> str:
    return {1: "once", 2: "twice"}.get(count, f"{count} times")


async def album_under_way(db: AsyncSession, entry: QueueEntry) -> bool:
    """For a song from an album queued whole: whether a song from that album has started since
    its requester queued it. Read from the play history, so a restart doesn't forget, and the
    same album queued again another day gets its shout-out again."""
    played = await db.scalar(
        select(func.count())
        .select_from(Play)
        .join(Track, Play.track_id == Track.id)
        .where(
            Play.requested_by == entry.requested_by,
            Play.played_at >= entry.added_at,
            Track.album == entry.track.album,
        )
    )
    return bool(played)


async def history(
    db: AsyncSession, entry: QueueEntry, requests: bool, named: str | None
) -> list[str]:
    """What the DJ might pick up on about the song coming up: how often it and its artist have
    played lately, and for a request, who asked for it before, the votes, and what else the
    requester has asked for. Nothing about requests unless the station announces them, and
    nobody named who opted out."""
    now = time.time()
    since = now - HISTORY_DAYS * 24 * 60 * 60
    track = entry.track
    lines = []

    plays = (
        await db.scalars(
            select(Play)
            .where(Play.track_id == track.id, Play.played_at >= since)
            .order_by(Play.played_at)
        )
    ).unique()
    plays = list(plays)
    if plays:
        line = (
            f"This song has played {_times(len(plays))} in the last week, most recently "
            f"{_ago(now - plays[-1].played_at)}"
        )
        askers = [play.requester for play in plays if play.requester]
        if requests and askers:
            counts = Counter(
                person.display_name if person.announce_requests else "someone" for person in askers
            )
            asked = [f"{name} ({_times(n)})" if n > 1 else name for name, n in counts.items()]
            line += f", requested by {_listed(asked)}"
        lines.append(line + ".")

    artist = track.artists.split(", ")[0]
    by_artist = or_(Track.artists == artist, Track.artists.like(f"{artist}, %"))
    artist_plays = await db.scalar(
        select(func.count()).select_from(Play).join(Track).where(Play.played_at >= since, by_artist)
    )
    if artist_plays >= 2:
        lines.append(f"{artist} has played {artist_plays} times in the last week.")

    if requests and entry.requested_by:
        tally = (await tallies(db, [entry.id])).get(entry.id)
        if tally and (tally.up or tally.down):
            lines.append(f"Votes on this request: {tally.up} up, {tally.down} down.")
        if named:
            theirs = list(
                (
                    await db.scalars(
                        select(Play).where(
                            Play.requested_by == entry.requested_by, Play.played_at >= since
                        )
                    )
                ).unique()
            )
            if theirs:
                same = sum(play.track.artists.split(", ")[0] == artist for play in theirs)
                line = f"Requests from {named} that played in the last week: {len(theirs)}"
                lines.append(line + (f", {same} of them by {artist}." if same else "."))
    return lines


@dataclass(frozen=True)
class Persona:
    """The DJ, as its station sets it up: a saved station or the editor's form."""

    dj: str
    station: str
    personality: str
    style: DJStyle
    tags: bool = False  # its voice understands audio tags such as [laughs]

    @classmethod
    def of(cls, station) -> Persona:
        return cls(
            station.dj_name,
            station.name,
            station.personality,
            station.style,
            is_eleven(station.voice),
        )


async def write_line(
    ai: AIClient,
    persona: Persona,
    context: str,
    before: Song | None,
    up_next: str,
    remarks: list[str],
    said: list[str],
    *,
    aware: bool,
) -> str:
    """What the DJ says before the next song. `said` is what it said the last few times.
    `aware` says whether the context has the weather and the news as well as the time."""
    parts = [context]
    if before:
        parts.append(f"Just played: {before}.")
    parts.append(up_next)
    if remarks:
        parts.append(" ".join(remarks))
    if said:
        parts.append(
            "What you said the last few times, oldest first. Don't repeat yourself, and vary how "
            "you start.\n" + "\n".join(f"- {line}" for line in said)
        )
    topics = "the weather, the time or the news" if aware else "the time"
    parts.append(f"Bring up {topics} only now and then, not every time.")
    parts.append(WHERE)
    instructions = INSTRUCTIONS.format(
        dj=persona.dj,
        station=persona.station,
        personality=persona.personality or "friendly",
        speech=TAGGED if persona.tags else PLAIN,
        style=STYLES[persona.style],
    )
    line = await ai.json(instructions, "\n\n".join(parts), "dj_line", LINE)
    return line["script"].strip()


def due(songs: int, minutes: float, every: int, unit: TalkUnit) -> bool:
    """Whether it's time to talk, `songs` songs or `minutes` minutes after it last did."""
    return songs >= every if unit == TalkUnit.TRACKS else minutes >= every


def voice_instructions(dj: str, personality: str) -> str:
    """How the text to speech should deliver the DJ's lines."""
    return f"Speak as {dj}, a radio DJ, live on air. Personality: {personality}"


@dataclass(frozen=True)
class Song:
    title: str
    artists: str

    def __str__(self) -> str:
        return f'"{self.title}" by {self.artists}'


class DJ:
    def __init__(
        self,
        sessionmaker,
        announcer: Announcer,
        ai: AIClient,
        speech: SpeechClient,
        awareness: Awareness,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessionmaker
        self._announcer = announcer
        self._ai = ai
        self._speech = speech
        self._awareness = awareness
        self._clock = clock
        self._tasks: set[asyncio.Task] = set()

    async def close(self) -> None:
        """Stop writing lines, before the database closes."""
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def settle(self) -> None:
        """Wait for lines being written. For tests."""
        await asyncio.gather(*self._tasks)

    async def lined_up(self, entry_id: int, key: str, opens: int | None = None) -> None:
        """A song was lined up on the speakers: maybe say something about it. Writing and
        voicing the line takes a few seconds, so it happens in the background."""
        task = asyncio.create_task(self._talk_safely(entry_id, key, opens))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _talk_safely(self, entry_id: int, key: str, opens: int | None) -> None:
        try:
            await self.talk(entry_id, key, opens)
        except (AIError, SpeechError) as error:
            log.warning("The DJ couldn't say anything this time: %s", error)
        except Exception:
            log.exception("The DJ failed")

    async def talk(self, entry_id: int, key: str, opens: int | None = None) -> Spoken | None:
        """Say something about the song lined up as `entry_id`, if it's time to. A song that
        `opens` a line-up's show, which runs until that minute, always gets a line opening the
        show. Returns the line queued, if any."""
        async with self._sessions() as db:
            source = await current_source(db)
            station = source.station if source and source.station_id else None
            entry = await db.get(QueueEntry, entry_id)
            if station is None or not station.dj or entry is None:
                return None
            playing = await in_state(db, EntryState.PLAYING)
            before = playing and Song(playing.track.title, playing.track.artists)
            after = Song(entry.track.title, entry.track.artists)
            requester = entry.requester
            named = (
                requester.display_name
                if requester and station.announce_requests and requester.announce_requests
                else None
            )
            remarks = await history(db, entry, station.announce_requests, named)
            picked = await db.get(PickNote, entry.track_id)
            note = picked.note if picked else None
            album = entry.track.album if entry.album_id else None
            starts_album = bool(album) and not await album_under_way(db, entry)
            zone = ZoneInfo(await get_pref(db, "timezone"))
            location = await get_pref(db, "weather_location")
            persona, voice = Persona.of(station), station.voice
            every, unit, aware = station.talk_every, station.talk_unit, station.global_awareness
            announcing, station_id = station.announce_requests, station.id
            memory = source.dj_memory or {}
            lineup = source.lineup.name if source.lineup else None

        # Talks on the first song after the station comes on, then as often as it says, and
        # for a request: for an album queued whole, on its first song only.
        shout_out = bool(named) and (not album or starts_album)
        songs = memory.get("songs", every - 1) + 1
        now = self._clock().astimezone(zone)
        talked_at = memory.get("talked_at")
        minutes = math.inf if talked_at is None else (now.timestamp() - talked_at) / 60
        if not (due(songs, minutes, every, unit) or shout_out or opens is not None):
            await self._remember(station_id, {**memory, "songs": songs})
            return None

        # The DJ always knows the time, so it doesn't say good morning at four.
        context = await self._awareness.context(location, now) if aware else clock_line(now)
        up_next = f"Up next: {after}."
        if opens is not None:
            until = f"{opens // 60:02d}:{opens % 60:02d}"
            part = f", part of the {lineup} line-up," if lineup else ""
            up_next = (
                f"Your show, {persona.station}{part} starts now and runs until {until}. Open it: "
                "welcome everyone, and say what's on and until when. " + up_next
            )
        if requester and announcing and album:
            if starts_album:
                up_next += f" {named or 'Someone'} put on the whole of the album {album}, "
                up_next += "starting with this. Say their name." if named else "starting with this."
            else:
                up_next += f" It's from the album {album}, which {named or 'someone'} put on."
        elif requester and announcing:
            up_next += f" {named} requested it: say their name." if named else " It's a request."
        if note and not requester:
            up_next += f" Why it was picked: {note}"
        said = memory.get("said", [])
        script = await write_line(
            self._ai, persona, context, before, up_next, remarks, said, aware=aware
        )
        if not script:
            return None
        clip = await self._speech.say(
            script, voice, voice_instructions(persona.dj, persona.personality)
        )

        await self._remember(
            station_id,
            {
                "songs": 0,
                "talked_at": now.timestamp(),
                "said": [*said, script][-RECENT_LINES:],
            },
        )
        spoken = Spoken(
            script, clip, None, AnnounceMode.AFTER, dj=True, for_key=key, title=persona.dj
        )
        self._announcer.say(spoken)
        return spoken

    async def _remember(self, station_id: int, memory: dict[str, Any]) -> None:
        """Keep what the DJ knows on the source, so a restart doesn't lose it. Let go if the
        station went off meanwhile."""
        async with self._sessions() as db:
            source = await current_source(db)
            if source and source.station_id == station_id:
                source.dj_memory = memory
                await db.commit()
