"""What GuildFM is doing with the speakers, and the commands that change it.

GuildFM is either driving the speakers (it put the music in the Sonos queue and is in control)
or it isn't. While driving, anything else showing up on the speakers means someone took over
from the Sonos or Spotify app; GuildFM then steps aside until an admin presses Play.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from enum import StrEnum
from typing import Any

from guildfm.live import LiveHub
from guildfm.speakers import (
    QueueItem,
    Room,
    Snapshot,
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


TrackChange = Callable[[str | None, str | None], Awaitable[None]]
Source = Callable[[], Awaitable[list[QueueItem]]]


class PlaybackController:
    def __init__(
        self,
        speakers: SpeakerSystem,
        hub: LiveHub,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._speakers = speakers
        self._hub = hub
        self._clock = clock
        self._lock = asyncio.Lock()

        self._snapshot: Snapshot | None = None
        self._rooms: list[Room] = []
        self._error: str | None = None
        self._polls = 0

        self._in_control = False
        self._overridden = False
        self._items: list[QueueItem] = []  # GuildFM's part of the Sonos queue, in order
        self._position = 1  # where in `_items` the speakers last were, 1-based
        self._grace_until = 0.0
        self._mismatches = 0

        self._last_compared: dict[str, Any] | None = None
        self._last_sent_at = float("-inf")
        self.on_track_change: list[TrackChange] = []
        # Run after every reading of the speakers, so the queue can keep them fed.
        self.on_poll: list[Callable[[], Awaitable[None]]] = []
        # What to play when GuildFM takes the speakers over with nothing of its own left.
        self.source: Source | None = None

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
            self._error = str(error)
            await self._publish()
            return
        self._error = None
        self._snapshot = snapshot
        if snapshot.rooms:
            self._rooms = snapshot.rooms
        self._follow(snapshot)

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
            return
        if self._is_ours(snapshot):
            self._mismatches = 0
            if snapshot.queue_position:
                self._position = snapshot.queue_position
            return
        if self._clock() < self._grace_until:
            return
        # Two readings in a row, so a speaker mid-change doesn't count as a takeover.
        self._mismatches += 1
        if self._mismatches >= 2:
            self._in_control = False
            self._overridden = True
            self._mismatches = 0

    @property
    def in_control(self) -> bool:
        return self._in_control and not self._error

    @property
    def time_left(self) -> int | None:
        """Seconds left in the current track, or None when the speakers don't know."""
        track = self._snapshot.track if self._snapshot else None
        if track is None or not track.duration:
            return None
        return max(0, track.duration - track.position)

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
            },
            "group_volume": snapshot.group_volume if snapshot else None,
            "rooms": [asdict(room) for room in self._rooms],
        }

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
        # After a Stop, the speakers may still hold GuildFM's queue, paused where it was.
        untouched = bool(self._snapshot and self._items and self._is_ours(self._snapshot))
        if self._in_control or untouched:
            await self._call(self._speakers.play)
        else:
            remaining = self._items[self._position - 1 :]
            if not remaining and self.source:
                remaining = await self.source()
            if not remaining:
                raise NothingToPlay
            await self._call(self._speakers.take_over, remaining)
            self._items, self._position = remaining, 1
        self._in_control, self._overridden = True, False
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

    async def stop(self) -> None:
        """Silence the speakers and stop driving them, whoever was playing."""
        if self._snapshot and self._snapshot.transport in ACTIVE:
            await self._call(self._speakers.pause)
        self._in_control, self._overridden = False, False
        await self.poll()

    async def queue_next(self, item: QueueItem) -> None:
        """Line `item` up to play after the current track."""
        self._require_control()
        position = await self._call(self._speakers.add_next, item)
        self._items.insert(position - 1, item)

    async def play_now(self, item: QueueItem) -> None:
        """Play `item` straight away, taking the speakers over if GuildFM isn't driving them."""
        if self._in_control:
            position = await self._call(self._speakers.add_next, item)
            self._items.insert(position - 1, item)
            await self._call(self._speakers.play_position, position)
        else:
            await self._call(self._speakers.take_over, [item])
            self._items, self._position = [item], 1
        self._in_control, self._overridden = True, False
        self._settle()
        await self.poll()

    async def set_group_volume(self, volume: int) -> None:
        await self._call(self._speakers.set_group_volume, volume)
        await self.poll(full=True)

    async def set_room_volume(self, uid: str, volume: int) -> None:
        await self._call(self._speakers.set_room_volume, uid, volume)
        await self.poll(full=True)
