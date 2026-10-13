"""Searching Spotify for something to request."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.auth import require
from guildfm.db import get_session
from guildfm.models import User
from guildfm.permissions import Permission
from guildfm.prefs import get_pref
from guildfm.spotify import SpotifyBusy, SpotifyError, remember

router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_session)]
Searcher = Annotated[User, require(Permission.ADD_TRACKS)]
PER_PAGE = 20


class TrackOut(BaseModel):
    id: str
    title: str
    artists: str
    album: str
    duration: int  # seconds
    explicit: bool
    art_url: str | None


class ArtistOut(BaseModel):
    id: str
    name: str
    art_url: str | None


class SearchOut(BaseModel):
    tracks: list[TrackOut]
    artists: list[ArtistOut]
    next_offset: int | None


@router.get("/search")
async def search(
    _: Searcher,
    request: Request,
    db: Db,
    q: Annotated[str, Query(max_length=200)] = "",
    artist: Annotated[str | None, Query(max_length=200)] = None,
    offset: Annotated[int, Query(ge=0, le=900)] = 0,
) -> SearchOut:
    """Tracks for `q`, optionally only by `artist`. Artists are suggested on the first page."""
    query = q.strip()
    if artist:
        query = f'artist:"{artist}" {query}'.strip()
    if not query:
        raise HTTPException(422, "Type something to search for.")

    try:
        tracks, artists, more = await request.app.state.spotify.search(query, offset)
    except SpotifyBusy as error:
        raise HTTPException(503, str(error)) from None
    except SpotifyError as error:
        raise HTTPException(502, str(error)) from None

    await remember(db, tracks)
    if not await get_pref(db, "allow_explicit"):
        tracks = [track for track in tracks if not track.explicit]
    return SearchOut(
        tracks=[
            TrackOut(
                id=track.id,
                title=track.title,
                artists=track.artists,
                album=track.album,
                duration=round(track.duration_ms / 1000),
                explicit=track.explicit,
                art_url=track.art_url,
            )
            for track in tracks
        ],
        artists=[
            ArtistOut(id=a.id, name=a.name, art_url=a.art_url)
            for a in (artists[:4] if offset == 0 and not artist else [])
        ],
        next_offset=offset + PER_PAGE if more else None,
    )
