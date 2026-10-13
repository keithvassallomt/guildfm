"""Playback: what's on the speakers, and the admin controls."""

from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from guildfm.auth import ActiveUser, require
from guildfm.models import User
from guildfm.permissions import Permission
from guildfm.playback import NothingToPlay, NotInControl, PlaybackController
from guildfm.speakers import SpeakersRefused, SpeakersUnavailable

router = APIRouter(prefix="/playback")
Controls = Annotated[User, require(Permission.CONTROL_PLAYBACK)]


class VolumeIn(BaseModel):
    volume: int = Field(ge=0, le=100)


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
    except SpeakersRefused as error:
        raise HTTPException(409, str(error)) from None
    except SpeakersUnavailable as error:
        raise HTTPException(503, str(error)) from None


@router.get("")
async def state(_: ActiveUser, request: Request) -> dict[str, Any]:
    return controller(request).state()


@router.post("/play")
async def play(_: Controls, request: Request) -> dict[str, Any]:
    async with speakers_errors():
        await controller(request).play()
    return controller(request).state()


@router.post("/pause")
async def pause(_: Controls, request: Request) -> dict[str, Any]:
    async with speakers_errors():
        await controller(request).pause()
    return controller(request).state()


@router.post("/skip")
async def skip(_: Controls, request: Request) -> dict[str, Any]:
    """Skip the current song. The next request is lined up first, so the music carries on."""
    async with speakers_errors():
        await request.app.state.queue.skip()
    return controller(request).state()


@router.post("/stop")
async def stop(_: Controls, request: Request) -> dict[str, Any]:
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
