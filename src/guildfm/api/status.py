"""The admins' status page: how the speakers and each outside service are doing, the backups,
and the latest problems from the log."""

import shutil
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm import __version__
from guildfm.audio import FFMPEG
from guildfm.auth import require
from guildfm.backups import backups, made_at
from guildfm.db import get_session
from guildfm.health import Health
from guildfm.models import SpotifyAccount, User
from guildfm.permissions import Permission
from guildfm.playback import Status

router = APIRouter(prefix="/status")
Db = Annotated[AsyncSession, Depends(get_session)]
Admin = Annotated[User, require(Permission.CHANGE_SETTINGS)]

PLAYBACK_WORDS = {
    Status.PLAYING: "GuildFM is playing",
    Status.PAUSED: "GuildFM is paused",
    Status.STOPPED: "GuildFM is stopped",
    Status.IDLE: "GuildFM has run out of songs",
    Status.OVERRIDDEN: "Someone took over from the Sonos app",
}


class ServiceOut(BaseModel):
    key: str
    name: str
    # "off" is a service GuildFM isn't set up to use, "unused" one it hasn't needed yet.
    state: Literal["ok", "failing", "unused", "off"]
    detail: str  # what it's for or what's wrong, in words
    ok_at: datetime | None = None  # when it last worked
    failed_at: datetime | None = None  # when it last failed


class CreditsOut(BaseModel):
    used: int
    limit: int
    resets_at: datetime | None


class BackupsOut(BaseModel):
    folder: str
    count: int
    latest_at: datetime | None


class ProblemOut(BaseModel):
    at: datetime
    level: str
    source: str
    message: str
    count: int


class StatusOut(BaseModel):
    version: str
    started_at: datetime
    connected: int  # browsers with GuildFM open
    services: list[ServiceOut]
    credits: CreditsOut | None  # ElevenLabs, when it'll say
    backups: BackupsOut
    disk_free: int  # bytes free where the data folder is
    problems: list[ProblemOut]


def _when(epoch: float | None) -> datetime | None:
    return None if epoch is None else datetime.fromtimestamp(epoch, UTC)


def _service(key: str, name: str, health: Health, purpose: str) -> ServiceOut:
    state = health.state
    if state == "failing":
        detail = health.problem or "It failed."
    elif state == "unused":
        detail = f"{purpose} Not needed since GuildFM started."
    else:
        detail = purpose
    return ServiceOut(
        key=key,
        name=name,
        state=state,
        detail=detail,
        ok_at=_when(health.ok_at),
        failed_at=_when(health.failed_at),
    )


def _speakers(request: Request) -> ServiceOut:
    playback = request.app.state.playback
    state = playback.state()
    if playback.monitoring:
        detail = "Not in use while monitor mode is on: GuildFM plays in browsers instead."
        return ServiceOut(key="speakers", name="Sonos speakers", state="off", detail=detail)
    if state["error"]:
        return ServiceOut(
            key="speakers", name="Sonos speakers", state="failing", detail=state["error"]
        )
    rooms = len(state["rooms"])
    words = PLAYBACK_WORDS.get(playback.status, "")
    detail = f"{rooms} room{'' if rooms == 1 else 's'} answering. {words}."
    return ServiceOut(key="speakers", name="Sonos speakers", state="ok", detail=detail)


async def _spotify(request: Request, db: AsyncSession) -> ServiceOut:
    account = await db.get(SpotifyAccount, 1)
    if account:
        purpose = f"Search, and playlists from {account.display_name}'s account."
    else:
        purpose = "Search. No account is connected, so playlists can't be imported."
    return _service("spotify", "Spotify", request.app.state.spotify.health, purpose)


def _elevenlabs(request: Request) -> ServiceOut:
    speech = request.app.state.speech
    if not speech.eleven_ready:
        return ServiceOut(
            key="elevenlabs",
            name="ElevenLabs",
            state="off",
            detail="No key in .env, so only OpenAI's voices are offered, and no jingles are made.",
        )
    purpose = "The account's own voices, and the jingle generator's music."
    return _service("elevenlabs", "ElevenLabs", speech.eleven_health, purpose)


def _ffmpeg(request: Request) -> ServiceOut:
    loudness = request.app.state.settings.audio_loudness
    if loudness is None:
        state, detail = "off", "Turned off in .env, so voices play at the level they come."
    elif FFMPEG is None:
        state, detail = "failing", "Not installed, so voices play quieter than the music."
    else:
        state, detail = "ok", f"Evens voices and jingles out to {loudness:g} LUFS."
    return ServiceOut(key="ffmpeg", name="ffmpeg", state=state, detail=detail)


@router.get("")
async def status(_: Admin, request: Request, db: Db) -> StatusOut:
    state = request.app.state
    settings = state.settings
    openai = Health.together(state.ai.health, state.speech.openai_health)
    credits = await state.speech.eleven_credits()
    made = backups(settings.backups)
    return StatusOut(
        version=__version__,
        started_at=_when(state.started_at),
        connected=state.live.count,
        services=[
            _speakers(request),
            await _spotify(request, db),
            _service(
                "openai",
                "OpenAI",
                openai,
                "Song picks, the DJ's words, voices, the music news and covers.",
            ),
            _elevenlabs(request),
            _service(
                "weather",
                "Weather",
                state.awareness.weather_health,
                "For stations with global awareness, from Open-Meteo.",
            ),
            _ffmpeg(request),
        ],
        credits=credits
        and CreditsOut(used=credits.used, limit=credits.limit, resets_at=_when(credits.resets_at)),
        backups=BackupsOut(
            folder=str(settings.backups),
            count=len(made),
            latest_at=made_at(made[-1]).astimezone(UTC) if made else None,
        ),
        disk_free=shutil.disk_usage(settings.data_dir).free,
        problems=[
            ProblemOut(
                at=_when(problem.at),
                level=problem.level,
                source=problem.source,
                message=problem.message,
                count=problem.count,
            )
            for problem in state.problems.problems
        ],
    )
