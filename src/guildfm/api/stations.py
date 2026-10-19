"""AI stations for curators: making and editing them, putting one on, and hearing the DJ.

A station's DJ is a DJ of their own, who can host other stations too. The editor's form names the
DJ by id, or none for a new one, with their details: saving the station saves those to the DJ,
on every station they host."""

import time
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StringConstraints, model_validator
from pydantic_core import PydanticCustomError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.ai import AIError
from guildfm.api.jingles import JingleOut, media
from guildfm.api.schemas import TrackOut
from guildfm.auth import require
from guildfm.covers import painted_from
from guildfm.db import get_session
from guildfm.dj import voice_instructions
from guildfm.jingles import forget
from guildfm.models import (
    DJProfile,
    DJStyle,
    Jingle,
    Play,
    SourceState,
    Station,
    StationKind,
    TalkUnit,
    User,
)
from guildfm.permissions import Permission
from guildfm.playlists import current_source
from guildfm.prefs import get_pref, set_pref
from guildfm.rehearsal import rehearse
from guildfm.speech import MAX_TEXT, SpeechError, Voice

router = APIRouter(prefix="/stations")
Db = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[User, require(Permission.SWITCH_SOURCE)]
Maker = Annotated[User, require(Permission.CREATE_STATIONS)]
Player = Annotated[User, require(Permission.SWITCH_SOURCE)]


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Brief = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
DJName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)]
Personality = Annotated[str, StringConstraints(strip_whitespace=True, max_length=600)]
Words = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TEXT)]


class StationIn(BaseModel):
    name: Name
    description: Brief
    global_awareness: bool = False
    dj: bool = False
    dj_id: int | None = None  # the DJ these details are for; None for a new one
    dj_name: DJName = ""
    personality: Personality = ""
    voice: Voice = "marin"
    talk_every: int = Field(3, ge=1, le=120)
    talk_unit: TalkUnit = TalkUnit.TRACKS
    style: DJStyle = DJStyle.COMMENTARY
    announce_requests: bool = True
    jingles: bool = True

    @model_validator(mode="after")
    def dj_has_a_name(self) -> StationIn:
        if self.dj and not self.dj_name:
            raise PydanticCustomError("dj_name", "Give the DJ a name.")
        return self


class StationOut(BaseModel):
    id: int
    name: str
    kind: StationKind
    description: str
    global_awareness: bool
    dj: bool
    dj_id: int | None
    dj_name: str
    personality: str
    voice: str
    talk_every: int
    talk_unit: TalkUnit
    style: DJStyle
    announce_requests: bool
    jingles: bool
    art_url: str | None  # its cover, once OpenAI has painted one
    made_by: str | None
    playing: bool  # the station filling the gaps between requests
    last_played_at: datetime | None


class HourIn(StationIn):
    # For a saved station, so its recent picks are left out as they would be for real.
    station_id: int | None = None


class LineOut(BaseModel):
    where: Literal["over_intro", "between"]  # over the start of the song, or before it
    script: str


class SlotOut(BaseModel):
    track: TrackOut
    note: str  # why the AI picked it
    starts_at: datetime
    line: LineOut | None  # what the DJ says before this song or over its start
    jingle: JingleOut | None  # played in the pause before this song


class HourOut(BaseModel):
    slots: list[SlotOut]
    minutes: int  # how long the songs add up to


class CoverIn(BaseModel):
    """What to paint a cover from: the editor's name and description, saved or not."""

    name: Name
    description: Brief


class PreviewIn(BaseModel):
    text: Words
    voice: Voice
    dj_name: DJName = ""
    personality: Personality = ""


async def _out(db: AsyncSession, station: Station) -> StationOut:
    source = await current_source(db)
    last = await db.scalar(select(func.max(Play.played_at)).where(Play.station_id == station.id))
    return StationOut(
        id=station.id,
        name=station.name,
        kind=station.kind,
        description=station.description,
        global_awareness=station.global_awareness,
        dj=station.dj,
        dj_id=station.dj_id,
        dj_name=station.dj_name,
        personality=station.personality,
        voice=station.voice,
        talk_every=station.talk_every,
        talk_unit=station.talk_unit,
        style=station.style,
        announce_requests=station.announce_requests,
        jingles=station.jingles,
        art_url=station.art_url,
        made_by=station.creator.display_name if station.creator else None,
        playing=bool(source and source.station_id == station.id),
        last_played_at=datetime.fromtimestamp(last, UTC) if last else None,
    )


async def _station(db: AsyncSession, station_id: int, editing: bool = False) -> Station:
    station = await db.get(Station, station_id)
    if station is None:
        raise HTTPException(404, "That station doesn't exist any more.")
    if editing and station.kind == StationKind.AI_PICKS:
        raise HTTPException(409, "AI picks looks after itself.")
    return station


# What's the station's own; the DJ's details go to the DJ.
STATION_FIELDS = (
    "name",
    "description",
    "global_awareness",
    "talk_every",
    "talk_unit",
    "style",
    "announce_requests",
    "jingles",
)


async def _apply(db: AsyncSession, station: Station, body: StationIn) -> None:
    for field in STATION_FIELDS:
        setattr(station, field, getattr(body, field))
    station.host = await _host(db, body) if body.dj else None


async def _host(db: AsyncSession, body: StationIn) -> DJProfile:
    """The DJ the form describes: the one it names, with these details, or a new one."""
    host = None
    if body.dj_id is not None:
        host = await db.get(DJProfile, body.dj_id)
        if host is None:
            raise HTTPException(404, "That DJ doesn't exist any more.")
    same_name = select(DJProfile.id).where(func.lower(DJProfile.name) == body.dj_name.lower())
    if host is not None:
        same_name = same_name.where(DJProfile.id != host.id)
    if await db.scalar(same_name.limit(1)):
        raise HTTPException(
            409, f"There's already a DJ called {body.dj_name}. Choose them from the list instead."
        )
    if host is None:
        host = DJProfile(created_at=time.time())
        db.add(host)
    host.name, host.personality, host.voice = body.dj_name, body.personality, body.voice
    return host


@router.get("")
async def stations(_: Viewer, db: Db) -> list[StationOut]:
    """Stations by name, then AI picks."""
    rows = (await db.scalars(select(Station))).unique().all()
    ordered = sorted(rows, key=lambda s: (s.kind == StationKind.AI_PICKS, s.name.lower()))
    return [await _out(db, station) for station in ordered]


@router.post("", status_code=201)
async def create(body: StationIn, user: Maker, request: Request, db: Db) -> StationOut:
    """A new station. Its cover is painted in the background, in half a minute or so."""
    station = Station(created_by=user.id, created_at=time.time())
    await _apply(db, station, body)
    db.add(station)
    await db.commit()
    request.app.state.covers.paint_later(station.id)
    return await _out(db, station)


@router.post("/preview")
async def preview(body: PreviewIn, _: Maker, request: Request) -> FileResponse:
    """The DJ saying `text`, delivered in its personality, for the browser to play."""
    personality = body.personality or "friendly and upbeat"
    instructions = voice_instructions(body.dj_name or "the DJ", personality)
    try:
        clip = await request.app.state.speech.say(body.text, body.voice, instructions)
    except SpeechError as error:
        raise HTTPException(502, str(error)) from None
    return FileResponse(clip.path, media_type="audio/mpeg")


@router.post("/preview-hour")
async def preview_hour(body: HourIn, _: Maker, request: Request) -> HourOut:
    """An hour of the station as the editor has it, saved or not: the songs and the DJ's
    lines. Takes about a minute, and nothing is kept."""
    state = request.app.state
    try:
        slots = await rehearse(
            state.sessionmaker, state.radio, state.ai, state.awareness, body, body.station_id
        )
    except AIError as error:
        raise HTTPException(502, str(error)) from None
    if not slots:
        raise HTTPException(502, "None of the AI's picks could be found on Spotify. Try again.")
    seconds = sum(slot.track.duration_ms for slot in slots) / 1000
    return HourOut(
        slots=[
            SlotOut(
                track=TrackOut.of(slot.track),
                note=slot.note,
                starts_at=slot.starts_at,
                line=LineOut(where=slot.line.where, script=slot.line.script) if slot.line else None,
                jingle=JingleOut.of(slot.jingle) if slot.jingle else None,
            )
            for slot in slots
        ],
        minutes=round(seconds / 60),
    )


@router.get("/{station_id}")
async def station(station_id: int, _: Viewer, db: Db) -> StationOut:
    return await _out(db, await _station(db, station_id))


@router.put("/{station_id}")
async def change(station_id: int, body: StationIn, _: Maker, request: Request, db: Db):
    station = await _station(db, station_id, editing=True)
    # What its cover shows. Covers from before this was noted show the saved details.
    painted = station.art_for or painted_from(station.name, station.description)
    await _apply(db, station, body)
    await db.commit()
    # A new name or description gets a new cover, unless it was already painted from them.
    if station.art is None or painted_from(station.name, station.description) != painted:
        request.app.state.covers.paint_later(station.id)
    await request.app.state.queue.changed()
    return await _out(db, station)


@router.delete("/{station_id}", status_code=204)
async def delete(station_id: int, _: Maker, request: Request, db: Db) -> Response:
    station = await _station(db, station_id, editing=True)
    if await get_pref(db, "default_station") == station.id:
        await set_pref(db, "default_station", None)
    # Its station idents go with it: the database deletes the rows, and this the files.
    for jingle in await db.scalars(select(Jingle).where(Jingle.station_id == station.id)):
        forget(media(request), jingle)
    request.app.state.covers.forget(station)
    # A line-up playing it carries on without it: its slot becomes a gap.
    source = await db.get(SourceState, 1)
    lineup_id = source.lineup_id if source and source.station_id == station.id else None
    await db.delete(station)
    await db.commit()
    if lineup_id:
        await request.app.state.queue.keep_lineup_on(lineup_id)
    await request.app.state.queue.changed()
    return Response(status_code=204)


@router.post("/{station_id}/cover")
async def repaint(
    station_id: int, _: Maker, request: Request, db: Db, body: CoverIn | None = None
) -> StationOut:
    """Another cover for the station, painted while you wait: half a minute or so. From the
    editor's name and description when it sends them, saved or not."""
    await _station(db, station_id)
    asked = (body.name, body.description) if body else None
    try:
        await request.app.state.covers.paint(station_id, asked)
    except AIError as error:
        raise HTTPException(502, f"{error} No new cover this time.") from None
    db.expire_all()
    return await _out(db, await _station(db, station_id))


@router.post("/{station_id}/play")
async def play(station_id: int, user: Player, request: Request, db: Db) -> StationOut:
    """Make the station fill the gaps between requests, from the next song on. Its first songs
    take a moment to pick."""
    station = await _station(db, station_id)
    if await request.app.state.queue.switch(station):
        request.app.state.queue.note(f"{user.display_name} put {station.name} on")
    await request.app.state.schedule.try_start()
    return await _out(db, station)
