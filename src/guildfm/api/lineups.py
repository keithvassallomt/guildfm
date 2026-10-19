"""Line-ups for curators: planning the day as shows and playlists by the clock, and putting one
on. See lineups.py for how a line-up plays."""

import time
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, StringConstraints, model_validator
from pydantic_core import PydanticCustomError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.ai import AIError
from guildfm.auth import require
from guildfm.covers import painted_from
from guildfm.db import get_session
from guildfm.lineups import STEP, day_span, playlist_minutes
from guildfm.models import Lineup, LineupSlot, Playlist, SourceState, Station, User
from guildfm.permissions import Permission
from guildfm.playlists import covers
from guildfm.prefs import get_pref

router = APIRouter(prefix="/lineups")
Db = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[User, require(Permission.SWITCH_SOURCE)]
Planner = Annotated[User, require(Permission.PLAN_LINEUPS)]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
About = Annotated[str, StringConstraints(strip_whitespace=True, max_length=600)]


class SlotIn(BaseModel):
    start: int = Field(ge=0, le=24 * 60)  # minutes after midnight
    end: int = Field(ge=0, le=24 * 60)
    station_id: int | None = None
    playlist_id: int | None = None

    @model_validator(mode="after")
    def makes_sense(self) -> SlotIn:
        if (self.station_id is None) == (self.playlist_id is None):
            raise PydanticCustomError("slot", "Each slot is a show or a playlist.")
        if self.start % STEP or self.end % STEP:
            raise PydanticCustomError("slot", "Slots start and end on the quarter hour.")
        if self.start >= self.end:
            raise PydanticCustomError("slot", "A slot has to end after it starts.")
        return self


class LineupIn(BaseModel):
    name: Name
    description: About = ""
    slots: list[SlotIn] = Field(default_factory=list, max_length=96)

    @model_validator(mode="after")
    def no_overlaps(self) -> LineupIn:
        ordered = sorted(self.slots, key=lambda slot: slot.start)
        for before, after in zip(ordered, ordered[1:], strict=False):
            if after.start < before.end:
                raise PydanticCustomError("slots", "Two slots overlap.")
        return self


class CoverIn(BaseModel):
    """The editor's name and description, saved or not, to paint a cover from."""

    name: Name
    description: About = ""


class SlotOut(BaseModel):
    start: int
    end: int
    kind: Literal["show", "playlist"]
    station_id: int | None
    playlist_id: int | None
    name: str
    art_url: str | None  # the station's cover, or the playlist's first album cover
    dj_name: str | None  # a show's DJ, None without one
    minutes: int | None  # a playlist's own length


class LineupOut(BaseModel):
    id: int
    name: str
    description: str
    art_url: str | None
    slots: list[SlotOut]
    on: bool  # it's the source now
    made_by: str | None
    last_on_at: datetime | None


class ShowChoice(BaseModel):
    id: int
    name: str
    art_url: str | None
    dj_name: str | None


class PlaylistChoice(BaseModel):
    id: int
    name: str
    covers: list[str]
    minutes: int


class DayOut(BaseModel):
    start: int  # the earliest opening time in the playback hours, in minutes
    end: int  # the latest closing time


class ChoicesOut(BaseModel):
    """What the editor offers: the day it plans, and the shows and playlists to put on it."""

    day: DayOut
    shows: list[ShowChoice]
    playlists: list[PlaylistChoice]


async def slots_out(db: AsyncSession, slots: list[LineupSlot]) -> list[SlotOut]:
    lengths = await playlist_minutes(db, [slot.playlist_id for slot in slots if slot.playlist_id])
    out = []
    for slot in slots:
        if slot.station:
            station = slot.station
            out.append(
                SlotOut(
                    start=slot.start,
                    end=slot.end,
                    kind="show",
                    station_id=station.id,
                    playlist_id=None,
                    name=station.name,
                    art_url=station.art_url,
                    dj_name=station.dj_name if station.dj else None,
                    minutes=None,
                )
            )
        elif slot.playlist:
            art = await covers(db, slot.playlist_id, 1)
            out.append(
                SlotOut(
                    start=slot.start,
                    end=slot.end,
                    kind="playlist",
                    station_id=None,
                    playlist_id=slot.playlist_id,
                    name=slot.playlist.name,
                    art_url=art[0] if art else None,
                    dj_name=None,
                    minutes=lengths.get(slot.playlist_id, 0),
                )
            )
    return out


async def lineup_out(db: AsyncSession, lineup: Lineup) -> LineupOut:
    source = await db.get(SourceState, 1)
    return LineupOut(
        id=lineup.id,
        name=lineup.name,
        description=lineup.description,
        art_url=lineup.art_url,
        slots=await slots_out(db, lineup.slots),
        on=bool(source and source.lineup_id == lineup.id),
        made_by=lineup.creator.display_name if lineup.creator else None,
        last_on_at=datetime.fromtimestamp(lineup.last_on_at, UTC) if lineup.last_on_at else None,
    )


async def _lineup(db: AsyncSession, lineup_id: int) -> Lineup:
    lineup = await db.get(Lineup, lineup_id)
    if lineup is None:
        raise HTTPException(404, "That line-up doesn't exist any more.")
    return lineup


async def _fresh(db: AsyncSession, lineup_id: int) -> LineupOut:
    """A line-up read back after a change, with its new slots' stations and playlists."""
    db.expire_all()
    return await lineup_out(db, await _lineup(db, lineup_id))


async def _apply(db: AsyncSession, lineup: Lineup, body: LineupIn) -> None:
    """The form's name, description and slots, checked against the stations and playlists."""
    playlist_ids = [slot.playlist_id for slot in body.slots if slot.playlist_id]
    lengths = await playlist_minutes(db, playlist_ids)
    slots = []
    for slot in body.slots:
        if slot.station_id and await db.get(Station, slot.station_id) is None:
            raise HTTPException(409, "One of those stations doesn't exist any more.")
        if slot.playlist_id:
            playlist = await db.get(Playlist, slot.playlist_id)
            if playlist is None:
                raise HTTPException(409, "One of those playlists doesn't exist any more.")
            if slot.end - slot.start > lengths.get(slot.playlist_id, 0):
                raise HTTPException(
                    409, f"{playlist.name} isn't that long, so its slot can't run that long."
                )
        slots.append(LineupSlot(**slot.model_dump()))
    lineup.name, lineup.description = body.name, body.description
    lineup.slots = sorted(slots, key=lambda slot: slot.start)


@router.get("")
async def lineups(_: Viewer, db: Db) -> list[LineupOut]:
    """Every line-up, the one on first, then the most recently on."""
    found = (await db.scalars(select(Lineup))).unique().all()
    source = await db.get(SourceState, 1)
    on = source.lineup_id if source else None
    ordered = sorted(
        found, key=lambda lineup: (lineup.id != on, -(lineup.last_on_at or 0), lineup.name.lower())
    )
    return [await lineup_out(db, lineup) for lineup in ordered]


@router.get("/choices")
async def choices(_: Planner, db: Db) -> ChoicesOut:
    start, end = day_span(await get_pref(db, "schedule"))
    stations = (await db.scalars(select(Station))).unique().all()
    playlists = (await db.scalars(select(Playlist))).unique().all()
    lengths = await playlist_minutes(db, [playlist.id for playlist in playlists])
    return ChoicesOut(
        day=DayOut(start=start, end=end),
        shows=[
            ShowChoice(
                id=station.id,
                name=station.name,
                art_url=station.art_url,
                dj_name=station.dj_name if station.dj else None,
            )
            for station in sorted(stations, key=lambda s: s.name.lower())
        ],
        playlists=[
            PlaylistChoice(
                id=playlist.id,
                name=playlist.name,
                covers=await covers(db, playlist.id),
                minutes=lengths[playlist.id],
            )
            for playlist in sorted(playlists, key=lambda p: p.name.lower())
            if lengths.get(playlist.id, 0) >= STEP
        ],
    )


@router.post("", status_code=201)
async def create(body: LineupIn, user: Planner, request: Request, db: Db) -> LineupOut:
    lineup = Lineup(created_by=user.id, created_at=time.time())
    await _apply(db, lineup, body)
    db.add(lineup)
    await db.commit()
    request.app.state.covers.paint_later(lineup.id, kind="lineup")
    await request.app.state.queue.changed()
    return await _fresh(db, lineup.id)


@router.get("/{lineup_id}")
async def lineup(lineup_id: int, _: Viewer, db: Db) -> LineupOut:
    return await lineup_out(db, await _lineup(db, lineup_id))


@router.put("/{lineup_id}")
async def change(lineup_id: int, body: LineupIn, _: Planner, request: Request, db: Db):
    lineup = await _lineup(db, lineup_id)
    painted = lineup.art_for or painted_from(lineup.name, lineup.description)
    await _apply(db, lineup, body)
    await db.commit()
    if lineup.art is None or painted_from(lineup.name, lineup.description) != painted:
        request.app.state.covers.paint_later(lineup.id, kind="lineup")
    # If it's on, the next song follows the new plan.
    await request.app.state.queue.changed()
    return await _fresh(db, lineup.id)


@router.delete("/{lineup_id}", status_code=204)
async def delete(lineup_id: int, _: Planner, request: Request, db: Db) -> Response:
    """Delete a line-up. If it's on, nothing fills the gaps any more, as when a playing
    playlist is deleted."""
    lineup = await _lineup(db, lineup_id)
    request.app.state.covers.forget(lineup)
    await db.delete(lineup)
    await db.commit()
    await request.app.state.queue.changed()
    return Response(status_code=204)


@router.post("/{lineup_id}/cover")
async def repaint(
    lineup_id: int, _: Planner, request: Request, db: Db, body: CoverIn | None = None
) -> LineupOut:
    """Another cover, painted while you wait: half a minute or so. From the editor's name and
    description when it sends them, saved or not."""
    await _lineup(db, lineup_id)
    asked = (body.name, body.description) if body else None
    try:
        await request.app.state.covers.paint(lineup_id, asked, kind="lineup")
    except AIError as error:
        raise HTTPException(502, f"{error} No new cover this time.") from None
    return await _fresh(db, lineup_id)


@router.post("/{lineup_id}/play")
async def play(lineup_id: int, user: Viewer, request: Request, db: Db) -> LineupOut:
    """Make the line-up the source from the next song on, starting with the slot on now. It
    stays on from day to day until someone picks something else."""
    lineup = await _lineup(db, lineup_id)
    if await request.app.state.queue.switch(lineup):
        request.app.state.queue.note(f"{user.display_name} put the {lineup.name} line-up on")
    await request.app.state.schedule.try_start()
    return await _fresh(db, lineup_id)
