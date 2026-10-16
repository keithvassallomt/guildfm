"""The DJ: a voice on an AI station that introduces songs, comments on them and gives shout-outs
for requests, in the station's personality and voice.

GuildFM asks the DJ about each song as it's lined up on the speakers, about half a minute before
the current one ends. The DJ talks every so many songs or minutes, as the station says, and for
every request while announcing requests is on, unless the person who asked opted out. The AI
writes the line and chooses whether it goes over the start of the song or in a pause before it,
aiming for a mix. Lines go through the announcer, so announcements always go first.
"""

import asyncio
import logging
import time
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.ai import AIClient, AIError, object_schema
from guildfm.announcements import Announcer, Spoken
from guildfm.awareness import Awareness, clock_line
from guildfm.models import AnnounceMode, DJStyle, EntryState, Play, QueueEntry, TalkUnit, Track
from guildfm.playlists import current_source
from guildfm.prefs import get_pref
from guildfm.queue import in_state, tallies
from guildfm.radio import Radio
from guildfm.speech import SpeechClient, SpeechError, is_eleven

log = logging.getLogger(__name__)

RECENT_MODES = 4  # where the DJ talked lately, so the AI can mix it up
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
WHERE = (
    "Choose where it goes. over_intro talks over the first seconds of the next song, so keep it "
    "to one or two short sentences, under 12 seconds. between plays in a short pause before the "
    "next song and can run a little longer, under 25 seconds. Aim for a mix of the two."
)
LINE = object_schema(
    mode={"type": "string", "enum": ["over_intro", "between"]},
    script={"type": "string"},
)


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
    lately: list[str],
    said: list[str],
) -> tuple[str, str]:
    """What the DJ says before the next song, and where: "over_intro" or "between". `lately`
    is where it talked the last few times, and `said` what it said."""
    parts = [context]
    if before:
        parts.append(f"Just played: {before}.")
    parts.append(up_next)
    if remarks:
        parts.append(" ".join(remarks))
    if said:
        parts.append(
            "What you said the last few times, oldest first. Don't repeat yourself: bring up the "
            "weather, the time or the news only now and then, and vary how you start.\n"
            + "\n".join(f"- {line}" for line in said)
        )
    if lately:
        parts.append("Where you talked lately: " + ", ".join(lately) + ".")
    parts.append(WHERE)
    instructions = INSTRUCTIONS.format(
        dj=persona.dj,
        station=persona.station,
        personality=persona.personality or "friendly",
        speech=TAGGED if persona.tags else PLAIN,
        style=STYLES[persona.style],
    )
    line = await ai.json(instructions, "\n\n".join(parts), "dj_line", LINE)
    return line["mode"], line["script"].strip()


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
        radio: Radio,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sessions = sessionmaker
        self._announcer = announcer
        self._ai = ai
        self._speech = speech
        self._awareness = awareness
        self._radio = radio
        self._clock = clock
        self._monotonic = monotonic
        # For each station: songs lined up since the DJ last talked, and when that was.
        self._since: dict[int, tuple[int, float]] = {}
        self._where: deque[str] = deque(maxlen=RECENT_MODES)
        self._said: dict[int, deque[str]] = {}  # each station's last few lines
        # Albums queued whole that the DJ has seen start, by requester and album. Only the
        # first song of one is a shout-out.
        self._albums: set[tuple[int | None, str]] = set()
        self._tasks: set[asyncio.Task] = set()

    async def close(self) -> None:
        """Stop writing lines, before the database closes."""
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def settle(self) -> None:
        """Wait for lines being written. For tests."""
        await asyncio.gather(*self._tasks)

    async def lined_up(self, entry_id: int, key: str) -> None:
        """A song was lined up on the speakers: maybe say something about it. Writing and
        voicing the line takes a few seconds, so it happens in the background."""
        task = asyncio.create_task(self._talk_safely(entry_id, key))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _talk_safely(self, entry_id: int, key: str) -> None:
        try:
            await self.talk(entry_id, key)
        except (AIError, SpeechError) as error:
            log.warning("The DJ couldn't say anything this time: %s", error)
        except Exception:
            log.exception("The DJ failed")

    async def talk(self, entry_id: int, key: str) -> Spoken | None:
        """Say something about the song lined up as `entry_id`, if it's time to. Returns the
        line queued, if any."""
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
            album = entry.track.album if entry.album_id else None
            starts_album = bool(album) and (entry.requested_by, entry.album_id) not in self._albums
            if album:
                self._albums.add((entry.requested_by, entry.album_id))
            zone = ZoneInfo(await get_pref(db, "timezone"))
            location = await get_pref(db, "weather_location")
            persona, voice = Persona.of(station), station.voice
            every, unit, aware = station.talk_every, station.talk_unit, station.global_awareness
            announcing, station_id = station.announce_requests, station.id

        # Talks on the first song after the station comes on, then as often as it says, and
        # for a request: for an album queued whole, on its first song only.
        shout_out = bool(named) and (not album or starts_album)
        songs, last = self._since.get(station_id, (every - 1, float("-inf")))
        songs += 1
        if not (due(songs, (self._monotonic() - last) / 60, every, unit) or shout_out):
            self._since[station_id] = (songs, last)
            return None

        now = self._clock().astimezone(zone)
        # The DJ always knows the time, so it doesn't say good morning at four.
        context = await self._awareness.context(location, now) if aware else clock_line(now)
        up_next = f"Up next: {after}."
        if requester and announcing and album:
            if starts_album:
                up_next += f" {named or 'Someone'} put on the whole of the album {album}, "
                up_next += "starting with this. Say their name." if named else "starting with this."
            else:
                up_next += f" It's from the album {album}, which {named or 'someone'} put on."
        elif requester and announcing:
            up_next += f" {named} requested it: say their name." if named else " It's a request."
        note = self._radio.notes.get(entry.track_id)
        if note and not requester:
            up_next += f" Why it was picked: {note}"
        said = self._said.setdefault(station_id, deque(maxlen=RECENT_LINES))
        where, script = await write_line(
            self._ai, persona, context, before, up_next, remarks, list(self._where), list(said)
        )
        if not script:
            return None
        clip = await self._speech.say(
            script, voice, voice_instructions(persona.dj, persona.personality)
        )

        self._since[station_id] = (0, self._monotonic())
        self._where.append(where)
        said.append(script)
        mode = AnnounceMode.OVER if where == "over_intro" else AnnounceMode.AFTER
        spoken = Spoken(script, clip, None, mode, dj=True, for_key=key)
        self._announcer.say(spoken)
        return spoken
