"""What GuildFM is doing with the speakers, and the commands that change it.

GuildFM is either driving the speakers (it put the music in the Sonos queue and is in control)
or it isn't. While driving, anything else showing up on the speakers means someone took over
from the Sonos or Spotify app; GuildFM then steps aside until an admin presses Play, or until the
speakers are playing GuildFM's queue again.

GuildFM notes down what it put on the speakers, so after a restart it can tell whether they're
still playing its queue and carry on driving them. It keeps the speakers' queue short: a few
songs that have played, for Previous, the song on now and what's lined up after it. When the
speakers stop, Sonos goes back to the start of its queue; GuildFM keeps its own place instead.

The DJ's lines and jingles between songs go into the Sonos queue too, just before the song they
come before, so every room plays them in step. Once played, they come back out.
"""

import asyncio
import json
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from enum import StrEnum
from pathlib import Path
from typing import Any

from guildfm.live import LiveHub
from guildfm.speakers import (
    QueueItem,
    Room,
    Snapshot,
    SpeakersRefused,
    SpeakersUnavailable,
    SpeakerSystem,
    track_key,
)

log = logging.getLogger(__name__)

POLL_SECONDS = 1.0
OFFLINE_POLL_SECONDS = 5.0
FULL_EVERY = 5  # rooms and volumes are read on every fifth poll
GRACE_SECONDS = 4.0  # after a GuildFM command, the speakers take a moment to catch up
HEARTBEAT_SECONDS = 5.0  # state is re-sent at least this often, so positions stay fresh
RESTART_SECONDS = 5  # further into a song than this, Previous starts it again
KEEP_PLAYED = 3  # songs that have played kept on the speakers, so Previous can go back
CLIP_STOP_SECONDS = 10  # speakers stopping this soon after a clip was on stopped at its end
TAKE_BACK_READINGS = 3  # readings of the speakers back on GuildFM's queue before it drives them
ACTIVE = ("PLAYING", "TRANSITIONING")


class Status(StrEnum):
    OFFLINE = "offline"  # no speakers answering
    STOPPED = "stopped"  # GuildFM isn't driving the speakers
    PLAYING = "playing"
    PAUSED = "paused"
    IDLE = "idle"  # driving, but GuildFM's queue has run out
    OVERRIDDEN = "overridden"  # someone took over from the Sonos or Spotify app


class NotInControl(Exception):
    """The command needs GuildFM to be driving the speakers."""


class NothingToPlay(Exception):
    """Play was pressed, but GuildFM hasn't queued anything."""


class CantGoBack(Exception):
    """Previous was pressed, but going back would jump over a song already lined up."""


def _in_place(snapshot: Snapshot, items: list[QueueItem]) -> bool:
    """Whether the speakers are on GuildFM's queue where it lines up with `items`: the song on
    them is the one GuildFM has at that place in the queue."""
    track, position = snapshot.track, snapshot.queue_position
    return bool(
        snapshot.playing_our_queue
        and track
        and position
        and position <= len(items)
        and items[position - 1].key == track_key(track.uri)
    )


TrackChange = Callable[[str | None, str | None], Awaitable[None]]
Source = Callable[[], Awaitable[list[QueueItem]]]


class PlaybackController:
    def __init__(
        self,
        speakers: SpeakerSystem,
        hub: LiveHub,
        clock: Callable[[], float] = time.monotonic,
        memory: Path | None = None,
    ) -> None:
        self._speakers = speakers
        self._hub = hub
        self._clock = clock
        self._memory = memory  # where GuildFM notes what it put on the speakers
        self._lock = asyncio.Lock()

        self._snapshot: Snapshot | None = None
        self._read_at = 0.0  # when `_snapshot` was read
        self._rooms: list[Room] = []
        self._error: str | None = None
        self._polls = 0

        self._in_control = False
        self._overridden = False
        # Moved to other speakers since GuildFM last drove them, so Play takes them over afresh.
        self._switched = False
        self._items: list[QueueItem] = []  # GuildFM's part of the Sonos queue, in order
        self._position = 1  # where in `_items` the speakers last were, 1-based
        # Clips in `_items`, by key: what each is ("dj", "jingle" or "announcement"), and the song
        # it comes before ("" for an announcement, which goes straight after the current track).
        self._clips: dict[str, tuple[str, str]] = {}
        # Whether the source asks for crossfade, and what the speakers were last set to (None
        # for not known).
        self._wants_crossfade = False
        self._crossfading: bool | None = None
        self._grace_until = 0.0
        self._mismatches = 0
        self._back_readings = 0  # in a row, of the speakers back on GuildFM's queue
        self._clip_heard_at = float("-inf")  # when the speakers were last read playing a clip

        self._last_compared: dict[str, Any] | None = None
        self._last_sent_at = float("-inf")
        self.on_track_change: list[TrackChange] = []
        # Run after every reading of the speakers, so the queue can keep them fed.
        self.on_poll: list[Callable[[], Awaitable[None]]] = []
        # What to play when GuildFM takes the speakers over with nothing of its own left.
        self.source: Source | None = None
        # Whether playback hours are open and when that next changes, kept up by the scheduler.
        self.hours: dict[str, Any] | None = None
        # An announcement, the DJ or a jingle is on the speakers. Set by the announcer.
        self.announcing = False
        self.dj_talking = False
        self.jingle = False
        # Playing in browsers instead of on the speakers (monitor mode).
        self.monitoring = False

    # Remembering what's on the speakers, for after a restart

    def _remember(self) -> None:
        if self._memory is None:
            return
        notes = {
            "driving": self._in_control,
            "overridden": self._overridden,
            "items": [asdict(item) for item in self._items],
            "clips": self._clips,
        }
        draft = self._memory.with_suffix(".tmp")
        draft.write_text(json.dumps(notes))
        draft.replace(self._memory)

    async def pick_up(self) -> bool:
        """At startup: if the speakers are still playing the queue GuildFM put on them before a
        restart, carry on driving them rather than starting out stopped. The same song has to be
        playing at the same place in the queue, so a queue built in the Sonos app isn't mistaken
        for GuildFM's. True when it picked them up. A takeover from the Sonos app, before the
        restart or while GuildFM was down, still counts as one afterwards."""
        try:
            notes = json.loads(self._memory.read_text()) if self._memory else None
        except OSError, ValueError:
            notes = None
        if not notes:
            return False
        self._overridden = bool(notes.get("overridden"))
        if not notes.get("driving") or not notes.get("items"):
            return False
        try:
            snapshot = await self._call(self._speakers.snapshot, True)
        except SpeakersUnavailable, SpeakersRefused:
            return False
        # Taken as the starting point, so the next reading doesn't count as a change of song.
        self._snapshot, self._rooms = snapshot, snapshot.rooms
        items = [QueueItem(**item) for item in notes["items"]]
        position = snapshot.queue_position
        track = snapshot.track
        if not _in_place(snapshot, items):
            # Something else is on the speakers, put there while GuildFM was down.
            ours = snapshot.playing_our_queue and (
                track is None or track_key(track.uri) in {item.key for item in items}
            )
            if not ours:
                self._overridden = True
                self._remember()
            return False
        self._items, self._position, self._in_control = items, position, True
        self._clips = {key: tuple(clip) for key, clip in notes.get("clips", {}).items()}
        self._settle()  # the first readings can catch the speakers changing songs
        log.info("Picked the speakers back up where GuildFM left them")
        return True

    @property
    def current_key(self) -> str | None:
        """The song on the speakers, while GuildFM is driving them."""
        track = self._snapshot.track if self._snapshot else None
        return track_key(track.uri) if self._in_control and track else None

    @property
    def upcoming_keys(self) -> set[str]:
        """The songs GuildFM has lined up after the current one."""
        return {item.key for item in self._items[self._position :]} if self._in_control else set()

    # Reading the speakers

    async def _call(self, fn, *args):
        """Speaker calls block, so they run in a thread, one at a time."""
        async with self._lock:
            return await asyncio.to_thread(fn, *args)

    async def run(self) -> None:
        while True:
            try:
                await self.poll(full=self._polls % FULL_EVERY == 0)
                for callback in self.on_poll:
                    await callback()
            except Exception:
                log.exception("Reading the speakers failed")
            self._polls += 1
            await asyncio.sleep(OFFLINE_POLL_SECONDS if self._error else POLL_SECONDS)

    async def poll(self, full: bool = False) -> None:
        previous = self._snapshot
        try:
            snapshot = await self._call(self._speakers.snapshot, full or not self._rooms)
        except SpeakersUnavailable as error:
            if self._error is None:
                log.info("Lost the speakers: %s", error)
            self._error = str(error)
            await self._publish()
            return
        if self._error:
            log.info("The speakers are answering again")
        self._error = None
        self._snapshot, self._read_at = snapshot, self._clock()
        if snapshot.rooms:
            self._rooms = snapshot.rooms
        self._follow(snapshot)
        if snapshot.transport in ACTIVE and self.current_key in self._clips:
            self._clip_heard_at = self._clock()
        await self._trim()
        await self._fit_crossfade()

        before = previous.track.uri if previous and previous.track else None
        after = snapshot.track.uri if snapshot.track else None
        if before != after:
            for callback in self.on_track_change:
                await callback(before, after)
        await self._publish()

    def _is_ours(self, snapshot: Snapshot) -> bool:
        if not snapshot.playing_our_queue:
            return False
        if snapshot.track is None:
            return True
        return track_key(snapshot.track.uri) in {item.key for item in self._items}

    def _follow(self, snapshot: Snapshot) -> None:
        """Keep track of where GuildFM's queue has got to, and notice outside takeovers."""
        if not self._in_control:
            self._mismatches = 0
            self._take_back(snapshot)
            return
        if self._is_ours(snapshot):
            self._mismatches = 0
            # Stopped, the speakers go back to the start of their queue: GuildFM keeps its place.
            if snapshot.queue_position and snapshot.transport != "STOPPED":
                self._position = snapshot.queue_position
            return
        if self._clock() < self._grace_until:
            return
        # Two readings in a row, so a speaker mid-change doesn't count as a takeover.
        self._mismatches += 1
        log.info(
            "Not GuildFM's queue on the speakers: %s, %s, %s",
            snapshot.transport,
            snapshot.media_uri or "no media",
            snapshot.track.uri if snapshot.track else "no track",
        )
        if self._mismatches >= 2:
            log.info("Someone took over the speakers, so GuildFM stepped aside")
            self._in_control = False
            self._overridden = True
            self._mismatches = 0
            self._remember()

    def _take_back(self, snapshot: Snapshot) -> None:
        """After a takeover, drive the speakers again once they're playing GuildFM's queue where
        it lines up: the takeover wasn't one, or someone put GuildFM's queue back on from the
        Sonos app. Not while they're paused or stopped, which someone may want."""
        back = (
            self._overridden and snapshot.transport in ACTIVE and _in_place(snapshot, self._items)
        )
        self._back_readings = self._back_readings + 1 if back else 0
        if self._back_readings < TAKE_BACK_READINGS:
            return
        self._back_readings = 0
        self._in_control, self._overridden = True, False
        self._position = snapshot.queue_position
        self._remember()
        log.info("The speakers are back on GuildFM's queue, so it's driving them again")

    async def _trim(self) -> None:
        """Take what has played off the speakers: clips straight away, so Previous goes back a
        song rather than to the DJ, and songs once a few more have. The speakers can't wander
        back through the day, and the queue in the Sonos app stays short."""
        if not self._in_control or (self._snapshot and self._snapshot.transport == "STOPPED"):
            return
        before = range(min(self._position - 1, len(self._items)))
        clips = [index for index in before if self._items[index].key in self._clips]
        songs = [index for index in before if self._items[index].key not in self._clips]
        played = clips + songs[: max(0, len(songs) - KEEP_PLAYED)]
        for index in sorted(played, reverse=True):
            try:
                await self._call(self._speakers.remove, index + 1)
            except SpeakersUnavailable, SpeakersRefused:
                log.warning("Couldn't take what has played off the speakers", exc_info=True)
                break
            self._clips.pop(self._items.pop(index).key, None)
            self._position -= 1
        if played:
            self._remember()

    async def clear_ahead(self, keep: set[str]) -> None:
        """Take songs off the speakers that come after the current one but that GuildFM hasn't
        lined up, leaving `keep` and the clips. They're songs that had played, which the speakers
        went back to."""
        if not self._in_control:
            return
        ahead = range(self._position, len(self._items))
        stray = [
            index
            for index in ahead
            if self._items[index].key not in keep and self._items[index].key not in self._clips
        ]
        for index in reversed(stray):
            try:
                await self._call(self._speakers.remove, index + 1)
            except SpeakersUnavailable, SpeakersRefused:
                log.warning("Couldn't take a stray song off the speakers", exc_info=True)
                break
            del self._items[index]
        if stray:
            log.info("Took %s songs that had played back off the speakers", len(stray))
            self._remember()

    @property
    def in_control(self) -> bool:
        return self._in_control and not self._error

    @property
    def previous_action(self) -> str | None:
        """What Previous does now: "back" to the song before near the start of a song, as on
        any music player, or "restart" this one. None while GuildFM isn't driving, or when
        going back would jump over a song already lined up after this one: that song would
        then play in between with no place in the queue."""
        if not self._in_control:
            return None
        track = self._snapshot.track if self._snapshot else None
        early = track is None or track.position <= RESTART_SECONDS
        if not early or self._position == 1:
            return "restart"
        return "back" if len(self._items) <= self._position else None

    @property
    def time_left(self) -> int | None:
        """Seconds left in the current track, or None when the speakers don't know."""
        track = self._snapshot.track if self._snapshot else None
        if track is None or not track.duration:
            return None
        return max(0, track.duration - track.position)

    @property
    def stopped_after_clip(self) -> bool:
        """Whether the speakers stopped as one of GuildFM's clips ended. Sonos often does that
        at the end of the DJ, instead of going on to the song after it."""
        recent = self._clock() - self._clip_heard_at <= CLIP_STOP_SECONDS
        return self.status == Status.IDLE and recent

    @property
    def position(self) -> int:
        """Where in GuildFM's queue the speakers are, 1-based."""
        return self._position

    def seconds_left(self) -> float | None:
        """Like `time_left`, but counting on from when the speakers were last read."""
        left = self.time_left
        if left is None or self._snapshot.transport not in ACTIVE:
            return left
        return max(0.0, left - (self._clock() - self._read_at))

    @property
    def status(self) -> Status:
        if self._error:
            return Status.OFFLINE
        if self._overridden:
            return Status.OVERRIDDEN
        if not self._in_control or self._snapshot is None:
            return Status.STOPPED
        if self._snapshot.transport in ACTIVE:
            return Status.PLAYING
        if self._snapshot.transport == "PAUSED_PLAYBACK":
            return Status.PAUSED
        return Status.IDLE

    def state(self) -> dict[str, Any]:
        snapshot = self._snapshot
        track = snapshot.track if snapshot else None
        clip = self._clips.get(self.current_key or "")
        return {
            "status": self.status.value,
            "error": self._error,
            "coordinator": snapshot.coordinator_name if snapshot else None,
            "track": None
            if track is None
            else {
                "title": track.title,
                "artist": track.artist,
                "album": track.album,
                "art_url": track.art_url,
                "duration": track.duration,
                "position": track.position,
                "ours": track_key(track.uri) in {item.key for item in self._items},
                # Whether the speakers are playing it, whoever put it on: GuildFM can be
                # stopped while someone else's music plays.
                "playing": snapshot.transport in ACTIVE,
            },
            "previous": self.previous_action,
            "announcing": self.announcing or (clip is not None and clip[0] == "announcement"),
            "dj_talking": self.dj_talking or (clip is not None and clip[0] == "dj"),
            "jingle": self.jingle or (clip is not None and clip[0] == "jingle"),
            "group_volume": snapshot.group_volume if snapshot else None,
            "rooms": [asdict(room) for room in self._rooms],
            "hours": self.hours,
            "monitor": self.monitoring,
        }

    async def publish(self) -> None:
        """Broadcast the state now, such as when an announcement starts or ends."""
        self._last_compared = None
        await self._publish()

    async def _publish(self) -> None:
        """Broadcast the state when something other than the play position changed."""
        state = self.state()
        compared = {**state, "track": state["track"] and {**state["track"], "position": None}}
        now = self._clock()
        if compared != self._last_compared or now - self._last_sent_at >= HEARTBEAT_SECONDS:
            self._last_compared = compared
            self._last_sent_at = now
            await self._hub.broadcast("playback", state)

    # Commands

    def _settle(self) -> None:
        self._grace_until = self._clock() + GRACE_SECONDS
        self._mismatches = 0

    def _require_control(self) -> None:
        if not self._in_control:
            raise NotInControl

    async def play(self) -> None:
        """Resume, or take the speakers back and carry on from where GuildFM left off."""
        snapshot = self._snapshot
        # After a Stop, the speakers may still hold GuildFM's queue, paused where it was.
        untouched = bool(snapshot and self._items and self._is_ours(snapshot))
        resume = self._in_control or (untouched and not self._switched)
        # Stopped, the speakers went back to the start of their queue: GuildFM goes on from its
        # own place instead, with what it has lined up, or else what's next from the source.
        stopped = bool(snapshot and snapshot.transport == "STOPPED")
        if resume and stopped and snapshot.track and self._position < len(self._items):
            await self._call(self._speakers.play_position, self._position + 1)
        elif resume and not stopped:
            await self._call(self._speakers.play)
        else:
            remaining = [] if resume and stopped else self._items[self._position - 1 :]
            if not remaining and self.source:
                remaining = await self.source()
            if not remaining:
                raise NothingToPlay
            await self._call(self._speakers.take_over, remaining)
            self._items, self._position = remaining, 1
            keys = {item.key for item in remaining}
            self._clips = {key: clip for key, clip in self._clips.items() if key in keys}
        self._in_control, self._overridden, self._switched = True, False, False
        self._remember()
        self._settle()
        await self.poll()

    async def pause(self) -> None:
        self._require_control()
        if self._snapshot and self._snapshot.transport in ACTIVE:
            await self._call(self._speakers.pause)
        self._settle()
        await self.poll()

    async def skip(self) -> None:
        self._require_control()
        await self._call(self._speakers.skip)
        self._settle()
        await self.poll()

    async def previous(self, action: str | None) -> None:
        """Carry out `previous_action`, read beforehand so the queue can get ready for it."""
        self._require_control()
        if action is None:
            raise CantGoBack
        position = self._position - 1 if action == "back" else self._position
        await self._call(self._speakers.play_position, position)
        self._settle()
        await self.poll()

    async def resume_after_break(self, ended: int) -> None:
        """Carry on after an announcement between songs: the song after the one at `ended`,
        from its start, or the end of that one if nothing follows it."""
        self._require_control()
        if ended < len(self._items):
            await self._call(self._speakers.play_position, ended + 1)
        else:
            await self._call(self._speakers.play)
        self._settle()
        await self.poll()

    async def stop(self) -> None:
        """Silence the speakers and stop driving them, whoever was playing."""
        if self._snapshot and self._snapshot.transport in ACTIVE:
            await self._call(self._speakers.pause)
        self._in_control, self._overridden = False, False
        self._remember()
        await self.poll()

    async def use(self, speakers: SpeakerSystem, monitoring: bool) -> None:
        """Play through `speakers` from now on: the Sonos system, or the monitor that plays in
        browsers. Whatever GuildFM was playing stops, and Play carries on from the same song in
        the new place."""
        if self._in_control and self._snapshot and self._snapshot.transport in ACTIVE:
            try:
                await self._call(self._speakers.pause)
            except SpeakersUnavailable, SpeakersRefused:
                log.warning("Couldn't pause the speakers on the way out", exc_info=True)
        async with self._lock:  # so no call to the old speakers is still under way
            self._speakers = speakers
        self.monitoring = monitoring
        self._in_control = self._overridden = False
        self._crossfading = None
        self._switched = True
        self._snapshot, self._rooms, self._error, self._mismatches = None, [], None, 0
        self._remember()
        # The starting point, read without counting as a change of song.
        try:
            snapshot = await self._call(self._speakers.snapshot, True)
        except SpeakersUnavailable as error:
            self._error = str(error)
        else:
            self._snapshot, self._read_at, self._rooms = snapshot, self._clock(), snapshot.rooms
        await self.publish()

    def _next_slot(self) -> int:
        """Where the next thing goes on the speakers: straight after the current track and any
        announcements waiting to play after it."""
        index = self._position
        while (
            index < len(self._items)
            and self._clips.get(self._items[index].key, ("", ""))[0] == "announcement"
        ):
            index += 1
        return index + 1

    async def queue_next(self, item: QueueItem) -> None:
        """Line `item` up to play after the current track, and after any announcement waiting."""
        self._require_control()
        position = await self._call(self._speakers.add_at, item, self._next_slot())
        self._items.insert(position - 1, item)
        self._remember()

    async def queue_announcement(self, item: QueueItem) -> None:
        """Line the clip `item` up to play straight after the current track, ahead of the next
        song and its jingle and DJ, and after any announcement already waiting there."""
        self._require_control()
        position = await self._call(self._speakers.add_at, item, self._next_slot())
        self._items.insert(position - 1, item)
        self._clips[item.key] = ("announcement", "")
        self._remember()
        await self._fit_crossfade()

    async def play_again(self, item: QueueItem) -> bool:
        """Have stopped speakers try the lined-up `item` once more. False if it isn't on them
        any more."""
        self._require_control()
        ahead = range(self._position, len(self._items))
        index = next((i for i in ahead if self._items[i].key == item.key), None)
        if index is None:
            return False
        await self._call(self._speakers.play_position, index + 1)
        self._settle()
        await self.poll()
        return True

    async def queue_before(self, item: QueueItem, key: str, kind: str) -> bool:
        """Line the clip `item` up to play just before the song `key`, which is lined up after
        the current track. `kind` is "dj" or "jingle". False if that song isn't lined up."""
        self._require_control()
        upcoming = range(self._position, len(self._items))
        index = next((i for i in upcoming if self._items[i].key == key), None)
        if index is None:
            return False
        position = await self._call(self._speakers.add_at, item, index + 1)
        self._items.insert(position - 1, item)
        self._clips[item.key] = (kind, key)
        self._remember()
        await self._fit_crossfade()
        return True

    async def unqueue(self, item: QueueItem) -> None:
        """Take `item` back off the speakers, if it's still to come, with any clips lined up to
        play just before it."""
        self._require_control()
        # Everything after the current track, latest first.
        for index in range(len(self._items) - 1, self._position - 1, -1):
            if self._items[index].key == item.key:
                first = index
                while (
                    first > self._position
                    and self._clips.get(self._items[first - 1].key, ("", ""))[1] == item.key
                ):
                    first -= 1
                for doomed in range(index, first - 1, -1):
                    await self._call(self._speakers.remove, doomed + 1)
                    self._clips.pop(self._items.pop(doomed).key, None)
                self._remember()
                return

    async def play_now(self, item: QueueItem) -> None:
        """Play `item` straight away, taking the speakers over if GuildFM isn't driving them."""
        if self._in_control:
            # After GuildFM's place, not wherever stopped speakers went back to.
            position = await self._call(self._speakers.add_at, item, self._position + 1)
            self._items.insert(position - 1, item)
            await self._call(self._speakers.play_position, position)
        else:
            await self._call(self._speakers.take_over, [item])
            self._items, self._position, self._clips = [item], 1, {}
        self._in_control, self._overridden, self._switched = True, False, False
        self._remember()
        self._settle()
        await self.poll()

    async def play_clip(self, uids: list[str] | None, url: str) -> list[str]:
        """Play the MP3 at `url` over whatever is on, in the rooms with `uids`, or every room for
        None, each at its own volume. Rooms on the TV are left out. Rooms go at the same time,
        outside the lock, so polling carries on. Returns the names of the rooms it played in.
        In monitor mode the browser plays it, whichever rooms it was for."""
        everywhere = uids is None or self.monitoring
        rooms = [r for r in self._rooms if not r.on_tv and (everywhere or r.uid in uids)]
        if not rooms:
            raise SpeakersUnavailable("None of its rooms can play it: they're off or on the TV.")
        # The rooms connect, then start together, so they're in step.
        start = threading.Barrier(len(rooms))
        results = await asyncio.gather(
            *(
                asyncio.to_thread(self._speakers.play_clip, r.uid, url, r.volume, start)
                for r in rooms
            ),
            return_exceptions=True,
        )
        played = [room.name for room, result in zip(rooms, results, strict=True) if result is None]
        for room, result in zip(rooms, results, strict=True):
            if isinstance(result, Exception):
                log.warning("Couldn't play a clip in %s: %s", room.name, result)
        if not played:
            failure = next(result for result in results if result is not None)
            if isinstance(failure, SpeakersUnavailable | SpeakersRefused):
                raise failure
            raise SpeakersUnavailable(f"The speakers couldn't play it: {failure}")
        return played

    async def own_address(self) -> str:
        """This machine's address on the speakers' network."""
        return await self._call(self._speakers.own_address)

    async def set_crossfade(self, on: bool) -> None:
        """Have the speakers fade each song into the next, or not, while GuildFM drives them.
        Never into or out of a clip, though: see `_fit_crossfade`."""
        self._wants_crossfade = on
        await self._fit_crossfade()

    async def _fit_crossfade(self) -> None:
        """Crossfade as the source asks, except while a clip is on or still to come. Sonos fades
        for ten seconds or more, longer than most clips, so the DJ, a jingle or an announcement
        would play under the songs either side. It comes back on once the song after the last
        clip is playing. Someone else's music keeps its own setting."""
        if not self._in_control:
            self._crossfading = None
            return
        ahead = self._items[max(self._position - 1, 0) :]
        on = self._wants_crossfade and not any(item.key in self._clips for item in ahead)
        if on == self._crossfading:
            return
        try:
            await self._call(self._speakers.set_crossfade, on)
        except SpeakersUnavailable, SpeakersRefused:
            log.warning("Couldn't change the speakers' crossfade", exc_info=True)
            return
        self._crossfading = on

    async def set_group_volume(self, volume: int) -> None:
        await self._call(self._speakers.set_group_volume, volume)
        await self.poll(full=True)

    async def set_room_volume(self, uid: str, volume: int) -> None:
        await self._call(self._speakers.set_room_volume, uid, volume)
        await self.poll(full=True)
