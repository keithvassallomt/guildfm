"""Announcements: scheduling them, playing one now, and hearing a voice before it goes out."""

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StringConstraints, model_validator
from pydantic_core import PydanticCustomError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.announcements import Announcer, CantAnnounce, upcoming
from guildfm.api.settings import HHMM
from guildfm.auth import require
from guildfm.db import get_session
from guildfm.models import Announcement, AnnouncementPlay, AnnounceMode, Repeat, User
from guildfm.permissions import Permission
from guildfm.prefs import DAYS, VOICES, get_pref
from guildfm.schedule import is_open
from guildfm.speech import MAX_TEXT, SpeechError

router = APIRouter(prefix="/announcements")
Db = Annotated[AsyncSession, Depends(get_session)]
Admin = Annotated[User, require(Permission.ANNOUNCE)]

RECENT = 10  # entries shown under "Recently played"
# An announcement scheduled for the minute it's made still plays.
SAME_MINUTE = 60

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TEXT)]


class RoomRef(BaseModel):
    uid: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=100)


class NowIn(BaseModel):
    text: Text
    # The rooms it plays in, or None for every room.
    rooms: Annotated[list[RoomRef], Field(min_length=1, max_length=20)] | None = None
    mode: AnnounceMode


class ScheduleIn(NowIn):
    start_date: date
    at: str = Field(pattern=HHMM)
    repeat: Repeat = Repeat.ONCE
    days: list[Literal[DAYS]] = []
    ends_on: date | None = None

    @model_validator(mode="after")
    def makes_sense(self) -> ScheduleIn:
        if self.repeat == Repeat.DAYS and not self.days:
            raise PydanticCustomError("days", "Pick at least one day.")
        if self.repeat != Repeat.ONCE and self.ends_on and self.ends_on < self.start_date:
            raise PydanticCustomError("ends_on", "It can't end before it starts.")
        return self


class ActiveIn(BaseModel):
    active: bool


class PreviewIn(BaseModel):
    text: Text
    voice: Literal[VOICES] | None = None  # the announcement voice from settings if left out


class AnnouncementOut(BaseModel):
    id: int
    text: str
    rooms: list[RoomRef] | None
    mode: AnnounceMode
    start_date: date
    at: str
    repeat: Repeat
    days: list[str]
    ends_on: date | None
    active: bool
    next_at: datetime | None  # when it next plays (if it's on), or None when it never will
    in_hours: bool  # whether that's inside playback hours


class LogOut(BaseModel):
    id: int
    text: str
    rooms: list[str] | None  # None for every room
    played_at: datetime
    problem: str | None  # why it didn't play, if it didn't


class AnnouncementsOut(BaseModel):
    scheduled: list[AnnouncementOut]  # soonest first, then any that are off
    recent: list[LogOut]  # newest first
    voice: str  # the announcement voice from settings


class PlayedOut(BaseModel):
    waits: bool  # it plays once the current song ends, rather than now


def announcer(request: Request) -> Announcer:
    return request.app.state.announcer


@asynccontextmanager
async def problems():
    """Turn text to speech and playback problems into messages the screen can show."""
    try:
        yield
    except SpeechError as error:
        raise HTTPException(502, str(error)) from None
    except CantAnnounce as error:
        raise HTTPException(409, str(error)) from None


class Office:
    """The time and playback hours, for working out when announcements next play."""

    def __init__(self, now: datetime, hours: dict[str, Any]) -> None:
        self.now, self.hours = now, hours

    @classmethod
    async def read(cls, db: AsyncSession, request: Request) -> Office:
        zone = ZoneInfo(await get_pref(db, "timezone"))
        return cls(announcer(request).now().astimezone(zone), await get_pref(db, "schedule"))

    def describe(self, rule: Announcement) -> AnnouncementOut:
        after = max(self.now, datetime.fromtimestamp(rule.handled_until, self.now.tzinfo))
        when = upcoming(rule, after, self.hours)
        return AnnouncementOut(
            id=rule.id,
            text=rule.text,
            rooms=rule.rooms,
            mode=rule.mode,
            start_date=rule.start_date,
            at=rule.at,
            repeat=rule.repeat,
            days=rule.days,
            ends_on=rule.ends_on,
            active=rule.active,
            next_at=when,
            in_hours=when is not None and is_open(self.hours, when),
        )


def _apply(rule: Announcement, body: ScheduleIn) -> None:
    rule.text = body.text
    rule.rooms = [room.model_dump() for room in body.rooms] if body.rooms else None
    rule.mode = body.mode
    rule.start_date = body.start_date
    rule.at = body.at
    rule.repeat = body.repeat
    rule.days = sorted(set(body.days), key=DAYS.index) if body.repeat == Repeat.DAYS else []
    rule.ends_on = body.ends_on if body.repeat != Repeat.ONCE else None


async def _changed(request: Request) -> None:
    announcer(request).refresh()
    await request.app.state.live.broadcast("announcements", {})


async def _find(db: AsyncSession, announcement_id: int) -> Announcement:
    rule = await db.get(Announcement, announcement_id)
    if rule is None:
        raise HTTPException(404, "That announcement has gone.")
    return rule


@router.get("")
async def everything(_: Admin, request: Request, db: Db) -> AnnouncementsOut:
    office = await Office.read(db, request)
    scheduled = [office.describe(rule) for rule in (await db.scalars(select(Announcement))).all()]
    scheduled.sort(key=lambda a: (not a.active, a.next_at is None, a.next_at or office.now, a.id))
    plays = await db.scalars(
        select(AnnouncementPlay).order_by(AnnouncementPlay.id.desc()).limit(RECENT)
    )
    return AnnouncementsOut(
        scheduled=scheduled,
        recent=[
            LogOut(
                id=play.id,
                text=play.text,
                rooms=play.rooms,
                played_at=datetime.fromtimestamp(play.played_at, UTC),
                problem=play.problem,
            )
            for play in plays
        ],
        voice=await get_pref(db, "announcement_voice"),
    )


@router.post("", status_code=201)
async def schedule(body: ScheduleIn, user: Admin, request: Request, db: Db) -> AnnouncementOut:
    # Made now, so it's ready when it's due, and any problem with OpenAI shows straight away.
    async with problems():
        await announcer(request).speak(body.text)
    made = announcer(request).now().timestamp()
    rule = Announcement(created_by=user.id, created_at=made, handled_until=made - SAME_MINUTE)
    _apply(rule, body)
    db.add(rule)
    await db.commit()
    await _changed(request)
    return (await Office.read(db, request)).describe(rule)


@router.post("/now")
async def now(body: NowIn, _: Admin, request: Request) -> PlayedOut:
    """Play an announcement straight away, or after the current song. It isn't kept."""
    rooms = [room.model_dump() for room in body.rooms] if body.rooms else None
    async with problems():
        waits = await announcer(request).announce_now(body.text, rooms, body.mode)
    return PlayedOut(waits=waits)


@router.post("/preview")
async def preview(body: PreviewIn, _: Admin, request: Request) -> FileResponse:
    """The MP3 for the browser to play. Previews never go to the office speakers."""
    async with problems():
        clip = await announcer(request).speak(body.text, body.voice)
    return FileResponse(clip.path, media_type="audio/mpeg")


@router.get("/{announcement_id}")
async def one(announcement_id: int, _: Admin, request: Request, db: Db) -> AnnouncementOut:
    return (await Office.read(db, request)).describe(await _find(db, announcement_id))


@router.put("/{announcement_id}")
async def change(
    announcement_id: int, body: ScheduleIn, _: Admin, request: Request, db: Db
) -> AnnouncementOut:
    rule = await _find(db, announcement_id)
    async with problems():
        await announcer(request).speak(body.text)
    _apply(rule, body)
    made = announcer(request).now().timestamp()
    rule.handled_until = max(rule.handled_until, made - SAME_MINUTE)
    await db.commit()
    await _changed(request)
    return (await Office.read(db, request)).describe(rule)


@router.patch("/{announcement_id}")
async def switch(
    announcement_id: int, body: ActiveIn, _: Admin, request: Request, db: Db
) -> AnnouncementOut:
    """Turn an announcement on or off. Times that passed while it was off don't play."""
    rule = await _find(db, announcement_id)
    if body.active and not rule.active:
        rule.handled_until = max(rule.handled_until, announcer(request).now().timestamp())
    rule.active = body.active
    await db.commit()
    await _changed(request)
    return (await Office.read(db, request)).describe(rule)


@router.delete("/{announcement_id}", status_code=204)
async def delete(announcement_id: int, _: Admin, request: Request, db: Db) -> Response:
    await db.delete(await _find(db, announcement_id))
    await db.commit()
    await _changed(request)
    return Response(status_code=204)


@router.post("/{announcement_id}/play")
async def play_now(announcement_id: int, _: Admin, request: Request, db: Db) -> PlayedOut:
    """Play a scheduled announcement now, over the music. Its schedule carries on as before."""
    rule = await _find(db, announcement_id)
    async with problems():
        await announcer(request).announce_now(rule.text, rule.rooms, AnnounceMode.OVER)
    return PlayedOut(waits=False)
