"""Monitor mode: GuildFM plays in a browser instead of on the Sonos speakers, so admins can try
things out without the office hearing.

`MonitorSystem` stands in for the speakers. It keeps GuildFM's queue and plays it on its own
clock: each song lasts as long as the real one would, and browsers play beeps for it, while
GuildFM's own clips (the DJ, jingles and announcements) play for real. `MonitorRelay` tells the
browsers what's playing, and admins who pressed Listen here hear it.
"""

import asyncio
import logging
import re
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse
from xml.sax.saxutils import unescape

from guildfm.live import LiveHub
from guildfm.speakers import QUEUE_URI, QueueItem, Room, Snapshot, Track

log = logging.getLogger(__name__)

MONITOR_UID = "GUILDFM_MONITOR"
SONG_SECONDS = 180.0  # for a song whose length GuildFM doesn't know
OVERLAYS_KEPT = 30.0  # seconds a clip over the music stays in the state, for late browsers
RELAY_SECONDS = 0.25
HEARTBEAT_SECONDS = 5.0  # the state is sent at least this often, so browsers keep in step
_TITLE = re.compile(r"<dc:title>(.*?)</dc:title>", re.DOTALL)


def _is_clip(item: QueueItem) -> bool:
    """An MP3 that GuildFM serves, such as the DJ between songs, rather than a song."""
    return item.uri.startswith("http")


def _title(item: QueueItem) -> str:
    found = _TITLE.search(item.metadata)
    return unescape(found.group(1)) if found else ""


class MonitorSystem:
    """The speakers as monitor mode has them: one room, the browser. Speaker calls come from
    worker threads and the relay from the event loop, so everything goes through a lock."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._queue: list[QueueItem] = []
        self._position: int | None = None  # 1-based
        self._ours = False  # GuildFM's queue is loaded, which it isn't until it takes over
        self._transport = "STOPPED"
        self._offset = 0.0  # seconds into the current item when it last started or paused
        self._since = 0.0  # the clock when it last started playing
        self._starts = 0  # items started so far, so browsers can tell one from the next
        self._volume = 20
        self._overlays: list[dict[str, Any]] = []  # clips over the music, newest last
        self._overlay_ids = 0
        self.version = 0  # goes up with every change, for the relay

    # Keeping time

    def _changed(self) -> None:
        self.version += 1

    def _current(self) -> QueueItem | None:
        if not self._ours or not self._position or self._position > len(self._queue):
            return None
        return self._queue[self._position - 1]

    def _elapsed(self) -> float:
        if self._transport == "PLAYING":
            return self._offset + self._clock() - self._since
        return self._offset

    def _start(self, position: int, at: float | None = None) -> None:
        """Play the item at `position` from the top, from `at` on the clock or now."""
        self._position, self._offset = position, 0.0
        self._since = self._clock() if at is None else at
        self._transport = "PLAYING"
        self._starts += 1
        self._changed()

    def _advance(self) -> None:
        """Move on past anything that has finished since the last look."""
        while self._transport == "PLAYING" and (item := self._current()):
            seconds = item.seconds or SONG_SECONDS
            ends = self._since - self._offset + seconds
            if self._clock() < ends:
                return
            if self._position < len(self._queue):
                self._start(self._position + 1, at=ends)
            else:
                self._transport, self._offset = "STOPPED", seconds
                self._changed()

    def tick(self) -> int:
        """Catch up with the clock. Returns `version`, which changes when anything does."""
        with self._lock:
            self._advance()
            gone = self._clock() - OVERLAYS_KEPT
            self._overlays = [overlay for overlay in self._overlays if overlay["at"] >= gone]
            return self.version

    def state(self) -> dict[str, Any]:
        """What a browser needs to play along."""
        with self._lock:
            self._advance()
            item, now = self._current(), self._clock()
            return {
                "transport": self._transport,
                "item": None
                if item is None
                else {
                    "id": self._starts,
                    "kind": "clip" if _is_clip(item) else "song",
                    "path": urlparse(item.uri).path if _is_clip(item) else None,
                    "seconds": item.seconds or SONG_SECONDS,
                },
                "elapsed": self._elapsed(),
                "volume": self._volume,
                "overlays": [
                    {
                        "id": overlay["id"],
                        "path": overlay["path"],
                        "volume": overlay["volume"],
                        "age": now - overlay["at"],
                    }
                    for overlay in self._overlays
                ],
            }

    # The SpeakerSystem interface

    def snapshot(self, full: bool) -> Snapshot:
        with self._lock:
            self._advance()
            item = self._current()
            track = None
            if item:
                seconds = item.seconds or SONG_SECONDS
                track = Track(
                    uri=item.uri,
                    title=_title(item),
                    artist="",
                    album="",
                    art_url=None,
                    duration=round(seconds),
                    position=int(min(self._elapsed(), seconds)),
                )
            room = Room(MONITOR_UID, "Monitor", "Browser", self._volume, True, False)
            return Snapshot(
                coordinator_uid=MONITOR_UID,
                coordinator_name="Monitor",
                transport=self._transport,
                media_uri=QUEUE_URI.format(uid=MONITOR_UID) if self._ours else "",
                track=track,
                queue_position=self._position if self._ours else None,
                group_volume=self._volume,
                rooms=[room] if full else [],
            )

    def play(self) -> None:
        with self._lock:
            self._advance()
            if self._current() is None or self._transport == "PLAYING":
                return
            if self._transport == "STOPPED":
                self._start(self._position)
            else:
                self._since, self._transport = self._clock(), "PLAYING"
                self._changed()

    def pause(self) -> None:
        with self._lock:
            self._advance()
            if self._transport == "PLAYING":
                self._offset, self._transport = self._elapsed(), "PAUSED_PLAYBACK"
                self._changed()

    def skip(self) -> None:
        with self._lock:
            self._advance()
            if self._position and self._position < len(self._queue):
                self._start(self._position + 1)
            else:
                self._transport = "STOPPED"
                self._changed()

    def set_group_volume(self, volume: int) -> None:
        with self._lock:
            self._volume = volume
            self._changed()

    def set_room_volume(self, uid: str, volume: int) -> None:
        self.set_group_volume(volume)

    def set_crossfade(self, on: bool) -> None:
        """Beeps have nothing to fade, so the monitor plays it straight."""

    def take_over(self, items: list[QueueItem]) -> None:
        with self._lock:
            self._queue, self._ours = list(items), True
            self._start(1)

    def add_next(self, item: QueueItem) -> int:
        with self._lock:
            self._advance()
            position = (self._position or 0) + 1
            self._queue.insert(position - 1, item)
            self._changed()
            return position

    def add_at(self, item: QueueItem, position: int) -> int:
        with self._lock:
            self._advance()
            self._queue.insert(position - 1, item)
            if self._position and position <= self._position:
                self._position += 1
            self._changed()
            return position

    def remove(self, position: int) -> None:
        with self._lock:
            self._advance()
            del self._queue[position - 1]
            if self._position and position < self._position:
                self._position -= 1
            self._changed()

    def play_position(self, position: int) -> None:
        with self._lock:
            self._start(position)

    def play_clip(
        self, uid: str, url: str, volume: int, start: threading.Barrier | None = None
    ) -> None:
        """Over whatever is on: browsers duck the beeps while it plays."""
        with self._lock:
            self._overlay_ids += 1
            self._overlays.append(
                {
                    "id": self._overlay_ids,
                    "path": urlparse(url).path,
                    "volume": volume,
                    "at": self._clock(),
                }
            )
            self._changed()

    def own_address(self) -> str:
        # Browsers fetch clips from wherever they reach GuildFM, so only the path matters.
        return "127.0.0.1"


class MonitorRelay:
    """Sends the monitor's state to browsers when it changes, and every few seconds while
    monitor mode is on."""

    def __init__(self, monitor: MonitorSystem, hub: LiveHub, on: Callable[[], bool]) -> None:
        self._monitor = monitor
        self._hub = hub
        self._on = on  # whether monitor mode is on
        self._sent: int | None = None
        self._sent_at = float("-inf")

    async def tick(self) -> None:
        if not self._on():
            self._sent = None
            return
        version, now = self._monitor.tick(), time.monotonic()
        if version != self._sent or now - self._sent_at >= HEARTBEAT_SECONDS:
            self._sent, self._sent_at = version, now
            await self._hub.broadcast("monitor", self._monitor.state())

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("Sending the monitor's state failed")
            await asyncio.sleep(RELAY_SECONDS)
