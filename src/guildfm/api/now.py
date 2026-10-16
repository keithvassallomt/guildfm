"""The Now Playing screen: where the music is coming from, the sources to switch between, and
what's played today."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.api.queue import PersonOut
from guildfm.api.schemas import TrackOut
from guildfm.auth import ActiveUser
from guildfm.db import get_session
from guildfm.models import EntryState, Play, Playlist, PlaylistKind, PlaylistTrack, Track, User
from guildfm.playlists import current_source
from guildfm.queue import in_state

router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_session)]

COVERS = 4  # album covers shown on a playlist's tile


class PlaylistTileOut(BaseModel):
    id: int
    name: str
    kind: PlaylistKind
    tracks: int
    shuffle: bool
    covers: list[str]  # album art from its first few songs
    last_played_at: datetime | None
    filling: bool  # the playlist filling the gaps between requests
    on_air: bool  # the current song came from it


class NowOut(BaseModel):
    # Where the current song came from, if GuildFM put it on.
    on_air: Literal["queue", "library", "radio"] | None
    requests_only: bool  # nothing fills the gaps between requests
    playlists: list[PlaylistTileOut]  # last played first


class PlayOut(BaseModel):
    id: int
    track: TrackOut
    played_at: datetime
    requested_by: PersonOut | None
    playlist: str | None
    upvotes: int
    downvotes: int


class HistoryOut(BaseModel):
    plays: list[PlayOut]  # newest first
    more: bool  # earlier plays today, fetched with ?before=<the last play's id>


def _when(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, UTC)


def _person(user: User | None) -> PersonOut | None:
    return PersonOut(id=user.id, display_name=user.display_name) if user else None


async def _covers(db: AsyncSession, playlist_id: int) -> list[str]:
    rows = await db.scalars(
        select(Track.art_url)
        .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
        .where(PlaylistTrack.playlist_id == playlist_id, Track.art_url.is_not(None))
        .order_by(PlaylistTrack.position)
    )
    covers: list[str] = []
    for url in rows:
        if url not in covers:
            covers.append(url)
            if len(covers) == COVERS:
                break
    return covers


@router.get("/now")
async def now(_: ActiveUser, db: Db) -> NowOut:
    source = await current_source(db)
    playing = await in_state(db, EntryState.PLAYING)
    on_air = None
    if playing:
        on_air = "queue" if playing.requested_by else "library" if playing.playlist_id else None

    counts = dict(
        (
            await db.execute(
                select(PlaylistTrack.playlist_id, func.count()).group_by(PlaylistTrack.playlist_id)
            )
        ).all()
    )
    last = dict(
        (
            await db.execute(
                select(Play.playlist_id, func.max(Play.played_at))
                .where(Play.playlist_id.is_not(None))
                .group_by(Play.playlist_id)
            )
        ).all()
    )
    playlists = (await db.scalars(select(Playlist))).unique().all()
    # Last played first. Ones that haven't played yet follow, Best Voted first, then by name.
    ordered = sorted(
        playlists,
        key=lambda p: (
            -last.get(p.id, 0),
            p.kind != PlaylistKind.BEST_VOTED,
            p.name.lower(),
        ),
    )
    return NowOut(
        on_air=on_air,
        requests_only=source is None,
        playlists=[
            PlaylistTileOut(
                id=playlist.id,
                name=playlist.name,
                kind=playlist.kind,
                tracks=counts.get(playlist.id, 0),
                shuffle=playlist.shuffle,
                covers=await _covers(db, playlist.id),
                last_played_at=_when(last[playlist.id]) if playlist.id in last else None,
                filling=bool(source and source.playlist_id == playlist.id),
                on_air=bool(playing and playing.playlist_id == playlist.id),
            )
            for playlist in ordered
        ],
    )


@router.get("/history")
async def history(
    _: ActiveUser,
    request: Request,
    db: Db,
    before: int | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> HistoryOut:
    """Today's plays, newest first, a page at a time."""
    since = await request.app.state.schedule.day_start()
    query = (
        select(Play)
        .where(Play.played_at >= since)
        .order_by(Play.id.desc())  # plays are added as they happen
        .limit(limit + 1)
    )
    if before is not None:
        query = query.where(Play.id < before)
    plays = list((await db.scalars(query)).unique().all())
    return HistoryOut(
        plays=[
            PlayOut(
                id=play.id,
                track=TrackOut.of(play.track),
                played_at=_when(play.played_at),
                requested_by=_person(play.requester),
                playlist=play.playlist.name if play.playlist else None,
                upvotes=play.upvotes,
                downvotes=play.downvotes,
            )
            for play in plays[:limit]
        ],
        more=len(plays) > limit,
    )
