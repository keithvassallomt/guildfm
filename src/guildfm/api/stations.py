"""AI stations for curators: making and editing them, putting one on, and hearing the DJ.

A station's DJs are DJs of their own, who can host other stations too. The editor's form names
each DJ by id, or none for a new one, with their details: saving the station saves those to the
DJ, on every station they host. The form takes a list of DJs, for a talk station (talk.md), or
the one DJ the editor had before."""

import time
from datetime import UTC, date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

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
from guildfm.hooks import changed_hooks, hooks_of, next_fresh
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
from guildfm.speech import MAX_TEXT, SpeechError, Voice, is_eleven
from guildfm.spotify import SpotifyBusy
from guildfm.talk import Host
from guildfm.talkshow import suggest_dynamic, together

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
Hook = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Obsession = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Dynamic = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Prompt = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
FeatureName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
FeatureDoes = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
MOST_DJS = 6
MOST_FEATURES = 8


class Feature(BaseModel):
    """One of a talk show's own recurring features: its name, and how it works."""

    name: FeatureName
    does: FeatureDoes


class NextHook(BaseModel):
    """The hook the AI rewrites next, and the morning it's new by."""

    hook: str  # "pet_peeves", "soft_spots" or "obsession"
    on: date


class DJIn(BaseModel):
    """One of a station's DJs: the one with this id, with these details, or a new one."""

    id: int | None = None
    name: DJName
    personality: Personality = ""
    voice: Voice = "marin"
    pet_peeves: Hook = ""
    soft_spots: Hook = ""
    obsession: Obsession = ""
    fresh_hooks: bool = True  # the AI rewrites a hook about monthly


class StationDJOut(BaseModel):
    id: int
    name: str
    personality: str
    voice: str
    pet_peeves: str
    soft_spots: str
    obsession: str
    fresh_hooks: bool
    next_hook: NextHook | None  # with fresh hooks on


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
    crossfade: bool = False
    # The station's DJs, in order, in place of the one DJ above when given. None keeps the
    # one-DJ form.
    djs: list[DJIn] | None = Field(None, max_length=MOST_DJS)
    dynamic: Dynamic = ""  # how its DJs get on
    talk_station: bool = False
    talk_ratio: int = Field(40, ge=20, le=100)  # percent of its time that's talk
    script_prompt: Prompt = ""
    features: list[Feature] = Field(default_factory=list, max_length=MOST_FEATURES)

    @model_validator(mode="after")
    def djs_make_sense(self) -> StationIn:
        names = [feature.name.lower() for feature in self.features]
        if len(set(names)) < len(names):
            raise PydanticCustomError("features", "Each feature needs a name of its own.")
        if self.djs is None and self.dj and not self.dj_name:
            raise PydanticCustomError("dj_name", "Give the DJ a name.")
        hosts = self.hosts()
        if any(not dj.name for dj in hosts):
            raise PydanticCustomError("djs", "Give every DJ a name.")
        names = [dj.name.lower() for dj in hosts]
        if len(set(names)) < len(names):
            raise PydanticCustomError("djs", "Each DJ on a station needs a name of their own.")
        if self.talk_station:
            if len(hosts) < 2:
                raise PydanticCustomError("djs", "A talk station needs two or more DJs.")
            openai = [dj.name for dj in hosts if not is_eleven(dj.voice)]
            if openai:
                raise PydanticCustomError(
                    "djs",
                    "A talk station's DJs need ElevenLabs voices, so they can talk over each "
                    "other: {names} {has} an OpenAI one.",
                    {"names": " and ".join(openai), "has": "has" if len(openai) == 1 else "have"},
                )
        return self

    def hosts(self) -> list[DJIn]:
        """The DJs the form describes, in order."""
        if self.djs is not None:
            return self.djs
        if not self.dj:
            return []
        return [
            DJIn(id=self.dj_id, name=self.dj_name, personality=self.personality, voice=self.voice)
        ]


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
    crossfade: bool  # the speakers fade each song into the next while it's on
    djs: list[StationDJOut]  # in order; the first is the one above
    dynamic: str
    talk_station: bool
    talk_ratio: int
    script_prompt: str
    features: list[Feature]
    art_url: str | None  # its cover, once OpenAI has painted one
    made_by: str | None
    playing: bool  # the station filling the gaps between requests
    last_played_at: datetime | None


class HourIn(StationIn):
    # For a saved station, so its recent picks are left out as they would be for real.
    station_id: int | None = None


class SlotOut(BaseModel):
    track: TrackOut
    note: str  # why the AI picked it
    starts_at: datetime
    line: str | None  # what the DJ says before this song
    jingle: JingleOut | None  # played in the pause before this song


class HourOut(BaseModel):
    slots: list[SlotOut]
    minutes: int  # how long the songs add up to


class CoverIn(BaseModel):
    """What to paint a cover from: the editor's name and description, saved or not."""

    name: Name
    description: Brief


class TogetherIn(BaseModel):
    """DJs as the editor has them, saved or not, for "Hear them together"."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] = ""
    djs: list[DJIn] = Field(min_length=2, max_length=MOST_DJS)
    dynamic: Dynamic = ""
    script_prompt: Prompt = ""

    @model_validator(mode="after")
    def can_talk_over_each_other(self) -> TogetherIn:
        openai = [dj.name for dj in self.djs if not is_eleven(dj.voice)]
        if openai:
            raise PydanticCustomError(
                "djs",
                "They need ElevenLabs voices to talk together: {names} {has} an OpenAI one.",
                {"names": " and ".join(openai), "has": "has" if len(openai) == 1 else "have"},
            )
        return self


class DynamicIn(BaseModel):
    """DJs as the editor has them, saved or not, for "Suggest one"."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] = ""
    djs: list[DJIn] = Field(min_length=2, max_length=MOST_DJS)
    script_prompt: Prompt = ""


class DynamicOut(BaseModel):
    dynamic: str


class PreviewIn(BaseModel):
    text: Words
    voice: Voice
    dj_name: DJName = ""
    personality: Personality = ""


def dj_out(dj: DJProfile, zone: ZoneInfo, now: float) -> StationDJOut:
    """A station's DJ, as the editor shows them, with the hook the AI rewrites next."""
    upcoming = None
    if dj.fresh_hooks:
        hook, on = next_fresh(dj, now, zone)
        upcoming = NextHook(hook=hook, on=on)
    return StationDJOut(
        id=dj.id,
        name=dj.name,
        personality=dj.personality,
        voice=dj.voice,
        pet_peeves=dj.pet_peeves,
        soft_spots=dj.soft_spots,
        obsession=dj.obsession,
        fresh_hooks=dj.fresh_hooks,
        next_hook=upcoming,
    )


async def _out(db: AsyncSession, station: Station) -> StationOut:
    source = await current_source(db)
    zone, now = ZoneInfo(await get_pref(db, "timezone")), time.time()
    last = await db.scalar(select(func.max(Play.played_at)).where(Play.station_id == station.id))
    return StationOut(
        id=station.id,
        name=station.name,
        kind=station.kind,
        description=station.description,
        global_awareness=station.global_awareness,
        dj=station.dj,
        dj_id=station.host.id if station.host else None,
        dj_name=station.dj_name,
        personality=station.personality,
        voice=station.voice,
        talk_every=station.talk_every,
        talk_unit=station.talk_unit,
        style=station.style,
        announce_requests=station.announce_requests,
        jingles=station.jingles,
        crossfade=station.crossfade,
        djs=[dj_out(dj, zone, now) for dj in station.hosts],
        dynamic=station.dynamic,
        talk_station=station.talk_station,
        talk_ratio=station.talk_ratio,
        script_prompt=station.script_prompt,
        features=[Feature(**feature) for feature in station.features or []],
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
    "crossfade",
    "dynamic",
    "talk_station",
    "talk_ratio",
    "script_prompt",
)


async def _apply(db: AsyncSession, station: Station, body: StationIn) -> None:
    for field in STATION_FIELDS:
        setattr(station, field, getattr(body, field))
    station.features = [feature.model_dump() for feature in body.features]
    # The one-DJ form has no hooks, so it leaves the DJ's alone.
    hooks = body.djs is not None
    station.set_hosts([await _host(db, dj, hooks) for dj in body.hosts()])


async def _host(db: AsyncSession, dj: DJIn, hooks: bool) -> DJProfile:
    """The DJ the form describes: the one it names, with these details, or a new one."""
    host = None
    if dj.id is not None:
        host = await db.get(DJProfile, dj.id)
        if host is None:
            raise HTTPException(404, "That DJ doesn't exist any more.")
    same_name = select(DJProfile.id).where(func.lower(DJProfile.name) == dj.name.lower())
    if host is not None:
        same_name = same_name.where(DJProfile.id != host.id)
    if await db.scalar(same_name.limit(1)):
        raise HTTPException(
            409, f"There's already a DJ called {dj.name}. Choose them from the list instead."
        )
    if host is None:
        host = DJProfile(created_at=time.time())
        db.add(host)
    host.name, host.personality, host.voice = dj.name, dj.personality, dj.voice
    if hooks:
        given = hooks_of(dj)
        host.hooks_at, host.old_hooks = changed_hooks(host, given, time.time())
        for hook, text in given.items():
            setattr(host, hook, text)
        host.fresh_hooks = dj.fresh_hooks
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


@router.post("/together")
async def hear_together(body: TogetherIn, _: Maker, request: Request, db: Db) -> FileResponse:
    """A half-minute exchange between the editor's DJs, saved or not, written and voiced the
    way a talk station's talk is, for the browser to play. About 200 ElevenLabs credits."""
    state = request.app.state
    now = datetime.now(UTC).astimezone(ZoneInfo(await get_pref(db, "timezone")))
    try:
        clip = await together(
            state.ai,
            state.speech,
            station=body.name or "GuildFM",
            hosts=[
                Host(dj.name, dj.personality, dj.pet_peeves, dj.soft_spots, dj.obsession)
                for dj in body.djs
            ],
            voices={dj.name: dj.voice for dj in body.djs},
            dynamic=body.dynamic,
            prompt=body.script_prompt,
            now=now,
        )
    except (AIError, SpeechError) as error:
        raise HTTPException(502, str(error)) from None
    return FileResponse(clip.path, media_type="audio/mpeg")


@router.post("/dynamic")
async def suggest(body: DynamicIn, _: Maker, request: Request) -> DynamicOut:
    """How the editor's DJs might get on, written by the AI from their personalities and
    hooks. A few seconds; nothing is kept."""
    try:
        dynamic = await suggest_dynamic(
            request.app.state.ai,
            station=body.name,
            hosts=[
                Host(dj.name, dj.personality, dj.pet_peeves, dj.soft_spots, dj.obsession)
                for dj in body.djs
            ],
            prompt=body.script_prompt,
        )
    except AIError as error:
        raise HTTPException(502, str(error)) from None
    return DynamicOut(dynamic=dynamic)


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
    except SpotifyBusy as error:
        raise HTTPException(503, str(error)) from None
    if not slots:
        raise HTTPException(502, "None of the AI's picks could be found on Spotify. Try again.")
    seconds = sum(slot.track.duration_ms for slot in slots) / 1000
    return HourOut(
        slots=[
            SlotOut(
                track=TrackOut.of(slot.track),
                note=slot.note,
                starts_at=slot.starts_at,
                line=slot.line,
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
    await request.app.state.queue.apply_crossfade()
    await request.app.state.queue.changed()
    return await _out(db, station)


@router.delete("/{station_id}", status_code=204)
async def delete(station_id: int, _: Maker, request: Request, db: Db) -> Response:
    station = await _station(db, station_id, editing=True)
    if await get_pref(db, "default_station") == station.id:
        await set_pref(db, "default_station", None)
    # Its station idents go with it: the database deletes the rows, and this the files. The
    # same for any in the jingle generator.
    for jingle in await db.scalars(select(Jingle).where(Jingle.station_id == station.id)):
        forget(media(request), jingle)
    composer = request.app.state.composer
    composer.forget_station(await composer.drafts(db, station.id))
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
    """Make the station fill the gaps between requests, from the next song on. Its first picks
    take a moment, so it opens with a song it has played before, if it has one."""
    station = await _station(db, station_id)
    if await request.app.state.queue.switch(station):
        request.app.state.queue.note(f"{user.display_name} put {station.name} on")
    await request.app.state.schedule.try_start()
    return await _out(db, station)
