"""Admin settings: reading them all, and changing any of them."""

from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from fastapi import APIRouter, Depends, Request
from pydantic import AfterValidator, BaseModel, Field, model_validator
from pydantic_core import PydanticCustomError
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.auth import require
from guildfm.db import get_session
from guildfm.models import User
from guildfm.permissions import Permission
from guildfm.prefs import QUEUE_RUNS_OUT, VOICES, all_prefs, set_pref

router = APIRouter(prefix="/settings")
Db = Annotated[AsyncSession, Depends(get_session)]
Admin = Annotated[User, require(Permission.CHANGE_SETTINGS)]

HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class Hours(BaseModel):
    on: bool
    start: str = Field(pattern=HHMM)
    end: str = Field(pattern=HHMM)

    @model_validator(mode="after")
    def opens_before_it_closes(self) -> Hours:
        if self.on and self.start >= self.end:
            raise PydanticCustomError("hours", "Opening time has to come before closing time.")
        return self


class Week(BaseModel):
    mon: Hours
    tue: Hours
    wed: Hours
    thu: Hours
    fri: Hours
    sat: Hours
    sun: Hours


def _zone(name: str) -> str:
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError, ValueError:
        raise PydanticCustomError("timezone", "That isn't a time zone GuildFM knows.") from None
    return name


class SettingsIn(BaseModel):
    """Any of the settings; the ones left out stay as they are."""

    request_cap: int | None = Field(None, ge=1, le=50)
    downvote_threshold: int | None = Field(None, ge=-50, le=-1)
    recently_played_hours: int | None = Field(None, ge=1, le=24 * 30)
    allow_explicit: bool | None = None
    best_voted_min_upvotes: int | None = Field(None, ge=1, le=100)
    best_voted_size: int | None = Field(None, ge=10, le=500)
    queue_runs_out: Literal[QUEUE_RUNS_OUT] | None = None
    schedule: Week | None = None
    timezone: Annotated[str, AfterValidator(_zone)] | None = None
    weather_location: str | None = Field(None, min_length=1, max_length=120)
    announcement_voice: Literal[VOICES] | None = None


class SettingsOut(BaseModel):
    values: dict[str, Any]
    voices: list[str]
    timezones: list[str]
    hours: dict[str, Any]


async def settings_out(db: AsyncSession, request: Request) -> SettingsOut:
    return SettingsOut(
        values=await all_prefs(db),
        voices=list(VOICES),
        timezones=sorted(available_timezones()),
        hours=await request.app.state.schedule.summary(),
    )


@router.get("")
async def read(_: Admin, request: Request, db: Db) -> SettingsOut:
    return await settings_out(db, request)


@router.patch("")
async def change(body: SettingsIn, _: Admin, request: Request, db: Db) -> SettingsOut:
    for key, value in body.model_dump(exclude_none=True).items():
        await set_pref(db, key, value)
    # Request caps, schedules and the like show on other screens; tell them to refresh.
    await request.app.state.queue.changed()
    await request.app.state.schedule.tick()
    await request.app.state.live.broadcast("playback", request.app.state.playback.state())
    return await settings_out(db, request)
