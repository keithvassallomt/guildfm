"""Announcements: an admin types one, and the office hears it, now or on a schedule.

Each is read out in the announcement voice from settings. If that's an ElevenLabs voice and
ElevenLabs fails (out of credits, say), OpenAI reads it out instead: the message matters more than
the voice. Over the music, it plays as an overlay clip in each chosen room: the music goes quiet
and comes back up. Between songs, one for every room goes into the Sonos queue straight after the
current song, so the rooms play it in step. One for chosen rooms can't, since a clip in the queue
plays in every room in the group: GuildFM pauses the music just before the current song ends,
plays an overlay clip in those rooms, then starts the next song.

Announcements only play while GuildFM is driving the speakers: not after Stop, an outside
takeover or closing time. Scheduled ones also keep to playback hours. One that comes due while
GuildFM can't play it is let go, and shows in the log as missed.

Everything spoken goes through one line, and announcements always go first, so the DJ's lines
and jingles (stage 10) wait for them. The DJ and jingles only ever play between songs, from the
Sonos queue, just before their song: they're for every room anyway, and the rooms play their
queue in step, where clips sent to each room start a few milliseconds apart and sound echoey.
One that can't go in the queue in time is let go.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.live import LiveHub
from guildfm.models import Announcement, AnnouncementPlay, AnnounceMode, Repeat
from guildfm.playback import NotInControl, PlaybackController, Status
from guildfm.prefs import DAYS, DEFAULTS, get_pref
from guildfm.schedule import is_open
from guildfm.speakers import SpeakersRefused, SpeakersUnavailable, clip_item
from guildfm.speech import Clip, SpeechClient, SpeechError, is_eleven

log = logging.getLogger(__name__)

TICK_SECONDS = 1.0
RECHECK_SECONDS = 60  # the schedule is read at least this often, so settings changes count
LATE_SECONDS = 5 * 60  # one due this long ago, while GuildFM wasn't running, is let go
BREAK_AHEAD = 4  # seconds before a song ends that GuildFM gets ready to play one between songs
# How long before the end it pauses. The speakers report whole seconds, rounded down, so this
# lands up to a second before the real end, never after it.
BREAK_LEAD = 1.2
GAP_SECONDS = 0.5  # after a clip ends, before the next thing starts
QUEUE_AHEAD = 3  # seconds a song needs left for a clip to go into the Sonos queue behind it
INSTRUCTIONS = (
    "Read this out as an announcement over an office's speakers: clear, warm and unhurried, "
    "easy to follow from across the room."
)
WEEKDAYS = DAYS[:5]
STAND_IN = DEFAULTS["announcement_voice"]  # OpenAI's, for when an ElevenLabs voice fails
HOURLY_LOOKAHEAD = 24 * 8  # hours searched for the next one inside playback hours

# Why an announcement didn't play, by what GuildFM was doing at the time.
MISSED = {
    Status.STOPPED: "GuildFM was stopped",
    Status.OVERRIDDEN: "Someone had taken over from the Sonos app",
    Status.OFFLINE: "The speakers were offline",
}
# Why one can't play now.
BLOCKED = {
    Status.STOPPED: "GuildFM is stopped, and announcements stop with it. Press Play first.",
    Status.OVERRIDDEN: "Someone took over from the Sonos app. Press Play to take back control.",
    Status.OFFLINE: "Can't reach the speakers.",
}


class CantAnnounce(Exception):
    """GuildFM isn't driving the speakers, so announcements can't play. Fit to show people."""


def next_time(rule: Announcement, after: datetime) -> datetime | None:
    """When `rule` next plays after `after`, in `after`'s time zone (the office's), or None once
    it's finished. Playback hours aren't considered here."""
    zone = after.tzinfo
    hour, minute = (int(part) for part in rule.at.split(":"))
    first = datetime.combine(rule.start_date, time(hour, minute), zone)
    found: datetime | None = None
    if rule.repeat == Repeat.ONCE:
        found = first if first > after else None
    elif rule.repeat == Repeat.HOURLY:
        found = first
        if found <= after:
            found = after.replace(minute=minute, second=0, microsecond=0)
            if found <= after:
                found += timedelta(hours=1)
    else:
        days = {Repeat.DAILY: DAYS, Repeat.WEEKDAYS: WEEKDAYS}.get(rule.repeat, rule.days)
        start = max(rule.start_date, after.date())
        for offset in range(8):
            when = datetime.combine(start + timedelta(days=offset), time(hour, minute), zone)
            if when > after and DAYS[when.weekday()] in days:
                found = when
                break
    if found and rule.ends_on and found.date() > rule.ends_on:
        return None
    return found


def upcoming(rule: Announcement, after: datetime, hours: dict[str, Any]) -> datetime | None:
    """When `rule` will next actually play: a repeating one skips times outside playback hours.
    A one-off gives its time either way."""
    when = next_time(rule, after)
    if rule.repeat == Repeat.ONCE:
        return when
    for _ in range(HOURLY_LOOKAHEAD):
        if when is None or is_open(hours, when):
            return when
        when = next_time(rule, when)
    return None


def room_names(rooms: list[dict[str, str]] | None) -> list[str] | None:
    return [room["name"] for room in rooms] if rooms else None


@dataclass(frozen=True)
class Spoken:
    """Something to say on the speakers."""

    text: str
    clip: Clip
    rooms: list[dict[str, str]] | None  # [{"uid", "name"}], or None for every room
    mode: AnnounceMode
    dj: bool = False  # the DJ's lines and jingles wait for any announcement, and aren't logged
    # The song a DJ line or jingle plays before. They never go over music, so once that song
    # has started, they're dropped.
    for_key: str | None = None
    jingle: bool = False
    title: str | None = None  # what the Sonos app shows while it plays from the queue


class Announcer:
    def __init__(
        self,
        sessionmaker,
        controller: PlaybackController,
        speech: SpeechClient,
        hub: LiveHub,
        *,
        port: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._sessions = sessionmaker
        self._controller = controller
        self._speech = speech
        self._hub = hub
        self._port = port  # where the speakers fetch clips from
        self._clock = clock
        self.sleep = sleep  # waits while a clip plays
        self._pending: list[Spoken] = []
        self._next_check = 0.0  # when to read the schedule again, in seconds since the epoch
        self._wake = asyncio.Event()

    def now(self) -> datetime:
        return self._clock()

    def refresh(self) -> None:
        """Announcements changed: read the schedule again on the next tick."""
        self._next_check = 0.0
        self._wake.set()

    async def speak(self, text: str, voice: str | None = None) -> Clip:
        """`text` read out as an announcement, in `voice` or the one from settings."""
        if voice is None:
            async with self._sessions() as db:
                voice = await get_pref(db, "announcement_voice")
        return await self._speech.say(text, voice, INSTRUCTIONS)

    async def _read_out(self, text: str, voice: str) -> Clip:
        """Like `speak`, for an announcement that's going on the speakers: if ElevenLabs fails,
        OpenAI's stand-in voice reads it out instead."""
        try:
            return await self._speech.say(text, voice, INSTRUCTIONS)
        except SpeechError as error:
            if not is_eleven(voice):
                raise
            log.warning("ElevenLabs couldn't read an announcement out, so OpenAI did: %s", error)
            return await self._speech.say(text, STAND_IN, INSTRUCTIONS)

    def check_can_play(self) -> None:
        if not self._controller.in_control:
            raise CantAnnounce(BLOCKED.get(self._controller.status, BLOCKED[Status.STOPPED]))

    def say(self, spoken: Spoken) -> None:
        """Queue something to say. It plays on the next tick, or between songs."""
        self._pending.append(spoken)
        self._wake.set()

    async def announce_now(
        self, text: str, rooms: list[dict[str, str]] | None, mode: AnnounceMode
    ) -> bool:
        """Play an announcement straight away: over the music, or between songs after this one.
        True when it waits for the current song to end."""
        self.check_can_play()
        async with self._sessions() as db:
            voice = await get_pref(db, "announcement_voice")
        self.say(Spoken(text, await self._read_out(text, voice), rooms, mode))
        return mode == AnnounceMode.AFTER and self._controller.status == Status.PLAYING

    # Running

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("Announcements failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), TICK_SECONDS)
            self._wake.clear()

    async def tick(self) -> None:
        await self._check_schedule()
        await self._deliver()

    async def _check_schedule(self) -> None:
        """Queue up scheduled announcements that have come due."""
        now = self._clock()
        if now.timestamp() < self._next_check:
            return
        soonest = now.timestamp() + RECHECK_SECONDS
        logged = False
        async with self._sessions() as db:
            zone = ZoneInfo(await get_pref(db, "timezone"))
            hours = await get_pref(db, "schedule")
            voice = await get_pref(db, "announcement_voice")
            local = now.astimezone(zone)
            for rule in (await db.scalars(select(Announcement).where(Announcement.active))).all():
                due, handled = None, datetime.fromtimestamp(rule.handled_until, zone)
                # Only the latest time that's come due counts; any before it are long gone.
                while (when := next_time(rule, handled)) and when <= local:
                    due = handled = when
                if due:
                    rule.handled_until = due.timestamp()
                    logged |= await self._due(db, rule, due, local, hours, voice)
                later = next_time(rule, handled)
                if later is None:
                    await db.delete(rule)  # finished; the log keeps what it said
                else:
                    soonest = min(soonest, later.timestamp())
            await db.commit()
        self._next_check = soonest
        if logged:
            await self._hub.broadcast("announcements", {})

    async def _due(
        self,
        db: AsyncSession,
        rule: Announcement,
        when: datetime,
        now: datetime,
        hours: dict[str, Any],
        voice: str,
    ) -> bool:
        """`rule` came due at `when`: queue it, or let it go. True when that went in the log."""
        problem = None
        if not is_open(hours, when):
            # Repeating ones keep to playback hours without saying so.
            if rule.repeat != Repeat.ONCE:
                return False
            problem = "Outside playback hours"
        elif (now - when).total_seconds() > LATE_SECONDS:
            problem = "GuildFM wasn't running"
        elif not self._controller.in_control:
            problem = MISSED.get(self._controller.status, MISSED[Status.STOPPED])
        else:
            try:
                clip = await self._read_out(rule.text, voice)
            except SpeechError as error:
                problem = str(error)
            else:
                self.say(Spoken(rule.text, clip, rule.rooms, rule.mode))
                return False
        self._log(db, rule.text, rule.rooms, problem)
        return True

    def _log(self, db: AsyncSession, text: str, rooms, problem: str | None) -> None:
        db.add(
            AnnouncementPlay(
                text=text,
                rooms=room_names(rooms),
                played_at=self._clock().timestamp(),
                problem=problem,
            )
        )

    async def _record(self, results: list[tuple[Spoken, str | None]]) -> None:
        """Log how each announcement went: None for played, or why it didn't."""
        results = [(spoken, problem) for spoken, problem in results if not spoken.dj]
        if not results:
            return
        async with self._sessions() as db:
            for spoken, problem in results:
                self._log(db, spoken.text, spoken.rooms, problem)
            await db.commit()
        await self._hub.broadcast("announcements", {})

    # Delivery

    def _take(self, items: list[Spoken]) -> None:
        taken = {id(spoken) for spoken in items}
        self._pending = [spoken for spoken in self._pending if id(spoken) not in taken]

    async def _deliver(self) -> None:
        if not self._pending:
            return
        controller = self._controller
        if not controller.in_control:
            problem = MISSED.get(controller.status, MISSED[Status.STOPPED])
            items, self._pending = self._pending, []
            await self._record([(spoken, problem) for spoken in items])
            return
        current, upcoming = controller.current_key, controller.upcoming_keys
        self._pending = [
            s
            for s in self._pending
            if (s.for_key in (None, current) or s.for_key in upcoming)
            and not (s.dj and s.for_key == current)
        ]
        # Announcements first; the DJ waits until there are none left.
        group = [spoken for spoken in self._pending if not spoken.dj] or list(self._pending)
        playing = controller.status == Status.PLAYING
        left = controller.seconds_left()

        def now(spoken: Spoken) -> bool:
            if spoken.dj:
                return False  # only ever between songs
            if spoken.mode == AnnounceMode.OVER:
                return True
            return not playing or left is None  # no song ending to wait for

        ready = [spoken for spoken in group if now(spoken)]
        # The DJ's lines and jingles for the song lined up next go into the Sonos queue, and so
        # do announcements for every room between songs, ahead of them.
        queued = [
            spoken
            for spoken in group
            if spoken.mode == AnnounceMode.AFTER
            and (spoken.for_key in upcoming if spoken.dj else spoken.rooms is None)
        ]
        # An announcement between songs pauses the music towards the end of a song.
        between = [
            spoken for spoken in group if spoken.mode == AnnounceMode.AFTER and not spoken.dj
        ]
        if ready:
            self._take(ready)
            await self._play(ready)
        elif queued and playing and left is not None and left > QUEUE_AHEAD:
            self._take(queued)
            refused = await self._queue(queued)
            if refused:
                await self._between_songs(refused)
        elif between and left is not None and left <= BREAK_AHEAD:
            self._take(between)
            await self._between_songs(between)

    async def _play(self, items: list[Spoken]) -> None:
        """Play each clip in its rooms, one after another."""
        controller = self._controller
        results: list[tuple[Spoken, str | None]] = []
        try:
            address = await controller.own_address()
        except (SpeakersUnavailable, SpeakersRefused) as error:
            await self._record([(spoken, str(error)) for spoken in items])
            return
        try:
            for spoken in items:
                controller.announcing = not spoken.dj
                controller.dj_talking = spoken.dj and not spoken.jingle
                controller.jingle = spoken.jingle
                await controller.publish()
                url = self._url(address, spoken)
                uids = [room["uid"] for room in spoken.rooms] if spoken.rooms else None
                try:
                    await controller.play_clip(uids, url)
                except (SpeakersUnavailable, SpeakersRefused) as error:
                    results.append((spoken, str(error)))
                    continue
                await self.sleep(spoken.clip.seconds + GAP_SECONDS)
                results.append((spoken, None))
        finally:
            controller.announcing = controller.dj_talking = controller.jingle = False
            await controller.publish()
            await self._record(results)

    def _url(self, address: str, spoken: Spoken) -> str:
        """Where the speakers fetch `spoken` from. Port 80 is left out, in case the speakers report
        the address back without it: queued clips are known as GuildFM's by their address."""
        host = address if self._port == 80 else f"{address}:{self._port}"
        return f"http://{host}/media/{spoken.clip.media_path}"

    async def _queue(self, items: list[Spoken]) -> list[Spoken]:
        """Put clips in the Sonos queue so the rooms play them in step: the DJ's lines and
        jingles each just before its song, and announcements straight after the current song,
        ahead of them. Returns any the speakers wouldn't take, to play the old way."""
        controller = self._controller
        try:
            address = await controller.own_address()
        except SpeakersUnavailable, SpeakersRefused:
            return items
        queued: list[Spoken] = []
        refused: list[Spoken] = []
        for index, spoken in enumerate(items):
            url, seconds = self._url(address, spoken), spoken.clip.seconds
            try:
                if spoken.dj:
                    kind = "jingle" if spoken.jingle else "dj"
                    item = clip_item(url, spoken.title or "GuildFM", seconds=seconds)
                    await controller.queue_before(item, spoken.for_key, kind)
                else:
                    item = clip_item(url, "Announcement", seconds=seconds)
                    await controller.queue_announcement(item)
            except NotInControl:
                problem = MISSED.get(controller.status, MISSED[Status.STOPPED])
                await self._record([(spoken, problem) for spoken in items[index:]])
                break
            except (SpeakersUnavailable, SpeakersRefused) as error:
                log.warning("The Sonos queue wouldn't take a clip, so it pauses instead: %s", error)
                refused = items[index:]
                break
            queued.append(spoken)
        # In the log once it's on the speakers' queue: it plays when the song ends.
        await self._record([(spoken, None) for spoken in queued])
        return refused

    async def _between_songs(self, items: list[Spoken]) -> None:
        """Pause just before the current song ends, play the clips, then start the next song
        from the top. If the song ends first, the next one is paused and started again."""
        controller = self._controller
        await controller.poll()  # a fresh reading, for the timing
        ending = controller.position
        left = controller.seconds_left()
        if left is not None and left > BREAK_LEAD:
            await self.sleep(left - BREAK_LEAD)
        if not controller.in_control:
            problem = MISSED.get(controller.status, MISSED[Status.STOPPED])
            await self._record([(spoken, problem) for spoken in items])
            return
        try:
            await controller.pause()
        except SpeakersUnavailable, SpeakersRefused:
            log.warning("Couldn't pause for an announcement; playing it over the music")
        await self._play(items)
        # Unless someone pressed Play or Stop meanwhile.
        if controller.in_control and controller.status == Status.PAUSED:
            try:
                await controller.resume_after_break(ending)
            except SpeakersUnavailable, SpeakersRefused:
                log.warning("Couldn't start the music again after an announcement", exc_info=True)
