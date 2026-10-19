"""Playback: what's on the speakers, and the admin controls."""

from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.auth import ActiveUser, require
from guildfm.db import get_session
from guildfm.models import User
from guildfm.permissions import Permission
from guildfm.playback import CantGoBack, NothingToPlay, NotInControl, PlaybackController
from guildfm.prefs import set_pref
from guildfm.speakers import SpeakersRefused, SpeakersUnavailable

router = APIRouter(prefix="/playback")
Transport = Annotated[User, require(Permission.TRANSPORT)]
Controls = Annotated[User, require(Permission.CONTROL_PLAYBACK)]
Admin = Annotated[User, require(Permission.CHANGE_SETTINGS)]
Db = Annotated[AsyncSession, Depends(get_session)]


class VolumeIn(BaseModel):
    volume: int = Field(ge=0, le=100)


class MonitorIn(BaseModel):
    on: bool


def controller(request: Request) -> PlaybackController:
    return request.app.state.playback


@asynccontextmanager
async def speakers_errors():
    """Turn playback problems into messages the admin screen can show."""
    try:
        yield
    except NotInControl:
        raise HTTPException(409, "GuildFM isn't driving the speakers. Press Play first.") from None
    except NothingToPlay:
        raise HTTPException(409, "There's nothing to play yet.") from None
    except CantGoBack:
        raise HTTPException(
            409, "The next song is already lined up, so there's no going back."
        ) from None
    except SpeakersRefused as error:
        raise HTTPException(409, str(error)) from None
    except SpeakersUnavailable as error:
        raise HTTPException(503, str(error)) from None


@router.get("")
async def state(_: ActiveUser, request: Request) -> dict[str, Any]:
    return controller(request).state()


@router.post("/play")
async def play(_: Transport, request: Request) -> dict[str, Any]:
    """Play, at any time: outside playback hours this overrides the schedule until Stop or the
    next closing time."""
    async with speakers_errors():
        await controller(request).play()
    return controller(request).state()


@router.post("/pause")
async def pause(_: Transport, request: Request) -> dict[str, Any]:
    async with speakers_errors():
        await controller(request).pause()
    return controller(request).state()


@router.post("/skip")
async def skip(_: Transport, request: Request) -> dict[str, Any]:
    """Skip the current song. The next request is lined up first, so the music carries on."""
    async with speakers_errors():
        await request.app.state.queue.skip()
    return controller(request).state()


@router.post("/previous")
async def previous(_: Transport, request: Request) -> dict[str, Any]:
    """Go back a song, or start this one again if it's more than a few seconds in."""
    async with speakers_errors():
        await request.app.state.queue.previous()
    return controller(request).state()


@router.post("/stop")
async def stop(_: Controls, request: Request) -> dict[str, Any]:
    request.app.state.schedule.stopped_by_hand()
    async with speakers_errors():
        await controller(request).stop()
    return controller(request).state()


@router.put("/volume")
async def group_volume(body: VolumeIn, _: Controls, request: Request) -> dict[str, Any]:
    async with speakers_errors():
        await controller(request).set_group_volume(body.volume)
    return controller(request).state()


@router.put("/rooms/{uid}/volume")
async def room_volume(uid: str, body: VolumeIn, _: Controls, request: Request) -> dict[str, Any]:
    async with speakers_errors():
        await controller(request).set_room_volume(uid, body.volume)
    return controller(request).state()


@router.get("/monitor")
async def monitor_state(_: Controls, request: Request) -> dict[str, Any]:
    """What the monitor is playing, for a browser that has just started listening."""
    return request.app.state.monitor.state()


@router.put("/monitor")
async def monitor(body: MonitorIn, _: Admin, request: Request, db: Db) -> dict[str, Any]:
    """Monitor mode on or off: GuildFM plays in browsers instead of on the Sonos speakers, or
    back on them. Whatever was playing stops, and GuildFM waits for Play."""
    playback = controller(request)
    if body.on != playback.monitoring:
        request.app.state.schedule.stopped_by_hand()
        app = request.app.state
        await playback.use(app.monitor if body.on else app.sonos, monitoring=body.on)
    await set_pref(db, "monitor", body.on)
    return playback.state()
