"""Connecting the Spotify account that playlists are imported from."""

from datetime import UTC, datetime
from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.auth import require
from guildfm.db import get_session
from guildfm.models import SpotifyAccount, User
from guildfm.permissions import Permission
from guildfm.spotify import RECONNECT_SECONDS, NotConnected, SpotifyClient, SpotifyError

router = APIRouter(prefix="/spotify")
# Spotify sends people back here, outside /api, after they sign in on its page.
callback_router = APIRouter()

Db = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[User, require(Permission.MANAGE_PLAYLISTS)]
Admin = Annotated[User, require(Permission.CHANGE_SETTINGS)]
REMIND_DAYS = 14


class AccountOut(BaseModel):
    connected: bool
    display_name: str | None = None
    connected_at: datetime | None = None
    reconnect_by: datetime | None = None
    reconnect_soon: bool = False
    playlists: int | None = None
    problem: str | None = None


class ConnectOut(BaseModel):
    url: str


def spotify(request: Request) -> SpotifyClient:
    return request.app.state.spotify


def _when(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, UTC)


@router.get("/account")
async def account(_: Viewer, request: Request, db: Db) -> AccountOut:
    row = await db.get(SpotifyAccount, 1)
    if row is None:
        return AccountOut(connected=False)
    try:
        playlists = await spotify(request).playlist_count(db)
    except NotConnected as error:
        return AccountOut(connected=False, problem=str(error))
    except SpotifyError as error:
        playlists, problem = None, str(error)
    else:
        problem = None
    reconnect_by = row.connected_at + RECONNECT_SECONDS
    now = datetime.now(UTC).timestamp()
    return AccountOut(
        connected=True,
        display_name=row.display_name,
        connected_at=_when(row.connected_at),
        reconnect_by=_when(reconnect_by),
        reconnect_soon=reconnect_by - now < REMIND_DAYS * 24 * 60 * 60,
        playlists=playlists,
        problem=problem,
    )


@router.post("/connect")
async def connect(_: Admin, request: Request) -> ConnectOut:
    """The Spotify sign-in link. It has to be opened on the GuildFM machine itself, because
    Spotify only sends people back to 127.0.0.1 for apps like this one."""
    return ConnectOut(url=spotify(request).authorize_url())


@router.delete("/account", status_code=204)
async def disconnect(_: Admin, db: Db) -> None:
    row = await db.get(SpotifyAccount, 1)
    if row is not None:
        await db.delete(row)
        await db.commit()


def _page(title: str, message: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title, quote=False)} · GuildFM</title></head>
<body style="margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#111316;color:#f3f1ea;font-family:system-ui,sans-serif;padding:24px">
<main style="max-width:420px;display:flex;flex-direction:column;gap:12px">
<h1 style="margin:0;font-size:28px">{escape(title, quote=False)}</h1>
<p style="margin:0;color:#a7adb5;line-height:1.5">{escape(message, quote=False)}</p>
<a href="/admin" style="color:#ff8a3d">Back to GuildFM</a></main></body></html>"""
    )


@callback_router.get("/auth/spotify/callback", include_in_schema=False)
async def callback(
    request: Request,
    db: Db,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    if error:
        return _page("Spotify wasn't connected", f"Spotify said: {error}. Try again from Admin.")
    if not state or not code or not spotify(request).accept_state(state):
        return _page("That link has expired", "Start again from GuildFM's Admin page.")
    try:
        account = await spotify(request).connect(db, code)
    except SpotifyError as problem:
        raise HTTPException(502, str(problem)) from None
    return _page(
        "Spotify connected",
        f"GuildFM can now read {account.display_name}'s playlists. "
        "You can close this tab and go back to GuildFM.",
    )
