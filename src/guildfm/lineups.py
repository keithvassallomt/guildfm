"""Line-ups: plans for the day, like a radio station's schedule. Each slot puts an AI station (a
show) or a playlist on for a stretch of the day, by the clock. In a gap, "When the queue runs
out" decides what plays.

A line-up is the source as a whole. The source row notes which one, and holds the station or
playlist of the slot that's on, so everything else plays that as usual. GuildFM follows the
line-up each time it lines up a song, by the time that song will start, so a slot starts at the
first song change after its start time and the day never drifts. A playlist still playing when
its slot ends is cut off there. When a show starts, its station ident and its DJ open it: the
queue tells them which song opens it, and until when the show runs.
"""

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.models import Lineup, LineupSlot, PlaylistTrack, SourceState, Station, Track
from guildfm.playlists import play_playlist, play_station
from guildfm.prefs import get_pref
from guildfm.radio import ai_picks

STEP = 15  # slots start and end on quarter hours
DEFAULT_DAY = (8 * 60, 18 * 60)  # with no playback hours set at all


def minutes(clock: str) -> int:
    """'08:30' to 510."""
    hours, mins = clock.split(":")
    return int(hours) * 60 + int(mins)


def clock(minute: int) -> str:
    """510 to '08:30'."""
    return f"{minute // 60:02d}:{minute % 60:02d}"


def minute_of(at: datetime) -> int:
    return at.hour * 60 + at.minute


def day_span(schedule: dict[str, Any]) -> tuple[int, int]:
    """The day a line-up plans: from the earliest opening time in the playback hours to the
    latest closing time."""
    days = [day for day in schedule.values() if day["on"]]
    if not days:
        return DEFAULT_DAY
    return min(minutes(day["start"]) for day in days), max(minutes(day["end"]) for day in days)


def slot_at(lineup: Lineup, minute: int) -> LineupSlot | None:
    """The slot on at `minute`, or None in a gap."""
    return next((slot for slot in lineup.slots if slot.start <= minute < slot.end), None)


async def gap_station(db: AsyncSession) -> Station:
    """What fills a gap, as when the queue runs out: the default station if the settings say
    so and there is one, otherwise AI picks."""
    station = None
    if await get_pref(db, "queue_runs_out") == "default_station":
        default = await get_pref(db, "default_station")
        station = default and await db.get(Station, default)
    return station or await ai_picks(db)


async def playlist_minutes(db: AsyncSession, playlist_ids: list[int]) -> dict[int, int]:
    """How long each playlist runs, in whole minutes."""
    rows = await db.execute(
        select(PlaylistTrack.playlist_id, func.sum(Track.duration_ms))
        .join(Track, Track.id == PlaylistTrack.track_id)
        .where(PlaylistTrack.playlist_id.in_(playlist_ids))
        .group_by(PlaylistTrack.playlist_id)
    )
    return {playlist_id: int((total or 0) // 60000) for playlist_id, total in rows.all()}


@dataclass(frozen=True)
class Opening:
    """A show starting: its station, and the minute it ends."""

    station_id: int
    until: int


@dataclass(frozen=True)
class Change:
    """What a line-up put on: its name, the line-up's, and the show it opens, if it's one."""

    name: str
    lineup: str
    opening: Opening | None


async def _target(db: AsyncSession, lineup: Lineup, minute: int):
    """What should be on at `minute`: the slot's playlist or station, or the gap's station.
    A playlist with no songs left counts as a gap. Returns (playlist, station, slot)."""
    slot = slot_at(lineup, minute)
    if slot and slot.playlist_id:
        count = await db.scalar(
            select(func.count()).where(PlaylistTrack.playlist_id == slot.playlist_id)
        )
        if count:
            return slot.playlist, None, slot
    if slot and slot.station_id:
        return None, slot.station, slot
    return None, await gap_station(db), None


async def _tune(db: AsyncSession, lineup: Lineup, minute: int, force: bool) -> Change | None:
    source = await db.get(SourceState, 1)
    playlist, station, slot = await _target(db, lineup, minute)
    same = bool(
        source
        and source.playlist_id == (playlist.id if playlist else None)
        and source.station_id == (station.id if station else None)
    )
    if same and not force:
        return None
    if same:
        # Already playing it, by hand: the line-up takes it over as it is.
        source.lineup_id = lineup.id
        await db.commit()
        return Change(name=(playlist or station).name, lineup=lineup.name, opening=None)
    if playlist:
        await play_playlist(db, playlist, lineup_id=lineup.id)
    else:
        await play_station(db, station, lineup_id=lineup.id)
    opening = Opening(station.id, slot.end) if slot and slot.station_id else None
    return Change(name=(playlist or station).name, lineup=lineup.name, opening=opening)


async def follow(db: AsyncSession, at: datetime) -> Change | None:
    """If a line-up is the source, put on what its slot at `at` (office time) says, unless
    that's on already. Returns what changed, if anything."""
    source = await db.get(SourceState, 1)
    if source is None or source.lineup_id is None:
        return None
    lineup = await db.get(Lineup, source.lineup_id)
    return await _tune(db, lineup, minute_of(at), force=False)


async def put_on(db: AsyncSession, lineup: Lineup, at: datetime) -> Change:
    """Make `lineup` the source, starting with the slot that covers `at` (office time)."""
    lineup.last_on_at = time.time()
    return await _tune(db, lineup, minute_of(at), force=True)
