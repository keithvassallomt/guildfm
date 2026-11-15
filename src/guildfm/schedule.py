"""Playback hours: GuildFM opens and closes by itself, in the office's time zone.

At opening time it starts playing if there's anything to play, or as soon as there is. At
closing time it stops everything. A Stop in between lasts until Play or the next opening.
Play pressed outside the hours plays for the after-hours time, then GuildFM stops again.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from guildfm.playback import NothingToPlay, PlaybackController
from guildfm.prefs import DAYS, get_pref
from guildfm.speakers import SpeakersRefused, SpeakersUnavailable

log = logging.getLogger(__name__)

CHECK_SECONDS = 20


def _clock(text: str) -> time:
    hours, minutes = text.split(":")
    return time(int(hours), int(minutes))


def is_open(schedule: dict[str, Any], now: datetime) -> bool:
    """Whether `now`, in the office's time zone, falls inside the playback hours."""
    day = schedule[DAYS[now.weekday()]]
    return day["on"] and _clock(day["start"]) <= now.time() < _clock(day["end"])


def next_change(schedule: dict[str, Any], now: datetime) -> datetime | None:
    """When GuildFM next opens or closes, or None if the schedule never changes."""
    open_now = is_open(schedule, now)
    for offset in range(8):
        date = (now + timedelta(days=offset)).date()
        day = schedule[DAYS[date.weekday()]]
        if not day["on"]:
            continue
        for edge, opens in ((day["start"], True), (day["end"], False)):
            moment = datetime.combine(date, _clock(edge), now.tzinfo)
            if moment > now and opens != open_now:
                return moment
    return None


class Scheduler:
    def __init__(
        self,
        sessionmaker,
        controller: PlaybackController,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessionmaker
        self._controller = controller
        self._clock = clock
        self._was_open: bool | None = None
        # Opened, but there was nothing to play yet: start as soon as there is.
        self.waiting_to_start = False
        # Playing outside the hours, after Play: when GuildFM stops again.
        self.after_hours_until: datetime | None = None

    async def _now(self) -> tuple[datetime, dict[str, Any]]:
        async with self._sessions() as db:
            schedule = await get_pref(db, "schedule")
            zone = ZoneInfo(await get_pref(db, "timezone"))
        return self._clock().astimezone(zone), schedule

    async def open_now(self) -> bool:
        now, schedule = await self._now()
        return is_open(schedule, now)

    async def day_start(self) -> float:
        """When today began in the office's time zone, as seconds since the epoch."""
        now, _ = await self._now()
        return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    async def _after_hours(self) -> float:
        async with self._sessions() as db:
            return await get_pref(db, "after_hours_play_hours")

    async def summary(self) -> dict[str, Any]:
        """For screens: whether GuildFM is open, when that changes, how long Play plays for
        outside the hours, and until when it's playing after hours, if it is."""
        now, schedule = await self._now()
        change = next_change(schedule, now)
        until = self.after_hours_until
        return {
            "open": is_open(schedule, now),
            "next_change": change and change.isoformat(),
            "after_hours": await self._after_hours(),
            "after_hours_until": until and until.isoformat(),
        }

    async def tick(self) -> None:
        now, schedule = await self._now()
        open_now = is_open(schedule, now)
        was_open, self._was_open = self._was_open, open_now
        # On startup there's no edge: GuildFM waits for the next opening time, or for Play.
        if was_open is not None and open_now != was_open:
            if open_now:
                log.info("Opening time")
                self.waiting_to_start = True
            else:
                log.info("Closing time")
                self.waiting_to_start = False
                await self._controller.stop()
        if open_now or not self._controller.in_control:
            self.after_hours_until = None
        elif self.after_hours_until is None:
            # Driving the speakers after hours without Play: picked back up after a restart,
            # say. The time starts now.
            await self._play_after_hours(now)
        elif now >= self.after_hours_until:
            log.info("After-hours play is over")
            self.after_hours_until = None
            await self._controller.stop()
        await self.try_start()
        self._controller.hours = await self.summary()

    async def played_by_hand(self) -> None:
        """Play was pressed. Outside the hours, GuildFM plays for the after-hours time from now,
        then stops again."""
        now, schedule = await self._now()
        if not is_open(schedule, now):
            await self._play_after_hours(now)
        self._controller.hours = await self.summary()

    async def _play_after_hours(self, now: datetime) -> None:
        # Counted in UTC, so a clock change in between doesn't make it an hour more or less.
        hours = timedelta(hours=await self._after_hours())
        self.after_hours_until = (now.astimezone(UTC) + hours).astimezone(now.tzinfo)
        log.info("Playing after hours until %s", f"{self.after_hours_until:%H:%M}")

    async def try_start(self) -> None:
        """Start playing if GuildFM opened and is still waiting for something to play."""
        if not self.waiting_to_start:
            return
        if self._controller.in_control:
            self.waiting_to_start = False
            return
        try:
            await self._controller.play()
        except NothingToPlay:
            return
        except SpeakersUnavailable, SpeakersRefused:
            log.warning("Couldn't start at opening time; trying again shortly", exc_info=True)
            return
        self.waiting_to_start = False

    def stopped_by_hand(self) -> None:
        """Stop was pressed: stay stopped until Play or the next opening time."""
        self.waiting_to_start = False
        self.after_hours_until = None

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("Checking the playback hours failed")
            await asyncio.sleep(CHECK_SECONDS)
