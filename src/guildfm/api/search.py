"""Searching Spotify for something to request."""

import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.api.schemas import TrackOut
from guildfm.auth import require
from guildfm.db import get_session
from guildfm.models import QueueEntry, User
from guildfm.permissions import Permission
from guildfm.prefs import get_pref
from guildfm.queue import recent_plays
from guildfm.spotify import SpotifyAlbum, SpotifyBusy, SpotifyError, remember

router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_session)]
Searcher = Annotated[User, require(Permission.ADD_TRACKS)]
PER_PAGE = 20
ALBUMS = 4  # albums suggested with the first page


class FoundTrackOut(TrackOut):
    queued: bool  # already in the queue, so it can't be requested again
    played_at: datetime | None  # when it last played, if recently


class ArtistOut(BaseModel):
    id: str
    name: str
    art_url: str | None


class AlbumOut(BaseModel):
    id: str
    name: str
    artists: str
    art_url: str | None
    year: str | None
    kind: str  # "album", "single" or "compilation"
    tracks: int

    @classmethod
    def of(cls, album: SpotifyAlbum) -> AlbumOut:
        return cls(**asdict(album))


class SearchOut(BaseModel):
    tracks: list[FoundTrackOut]
    artists: list[ArtistOut]
    albums: list[AlbumOut]  # on the first page, when asked for
    next_offset: int | None


@router.get("/search")
async def search(
    _: Searcher,
    request: Request,
    db: Db,
    q: Annotated[str, Query(max_length=200)] = "",
    artist: Annotated[str | None, Query(max_length=200)] = None,
    offset: Annotated[int, Query(ge=0, le=900)] = 0,
    albums: bool = False,
) -> SearchOut:
    """Tracks for `q`, optionally only by `artist`. Artists are suggested on the first page,
    and albums too with `albums`, for adding to a playlist."""
    query = q.strip()
    if artist:
        query = f'artist:"{artist}" {query}'.strip()
    if not query:
        raise HTTPException(422, "Type something to search for.")

    try:
        found = await request.app.state.spotify.search(query, offset, albums=albums)
    except SpotifyBusy as error:
        raise HTTPException(503, str(error)) from None
    except SpotifyError as error:
        raise HTTPException(502, str(error)) from None

    tracks = found.tracks
    await remember(db, tracks)
    if not await get_pref(db, "allow_explicit"):
        tracks = [track for track in tracks if not track.explicit]

    ids = [track.id for track in tracks]
    queued = set(await db.scalars(select(QueueEntry.track_id).where(QueueEntry.track_id.in_(ids))))
    since = time.time() - await get_pref(db, "recently_played_hours") * 3600
    plays = await recent_plays(db, since, ids)

    return SearchOut(
        tracks=[
            FoundTrackOut(
                **TrackOut.of(track).model_dump(),
                queued=track.id in queued,
                played_at=datetime.fromtimestamp(plays[track.id][-1], UTC)
                if track.id in plays
                else None,
            )
            for track in tracks
        ],
        artists=[
            ArtistOut(id=a.id, name=a.name, art_url=a.art_url)
            for a in (found.artists[:4] if offset == 0 and not artist else [])
        ],
        albums=[AlbumOut.of(album) for album in found.albums[:ALBUMS]],
        next_offset=offset + PER_PAGE if found.more else None,
    )
