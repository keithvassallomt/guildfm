"""The Now Playing screen: where the music is coming from, the sources to switch between, and
what's played today."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.api.schemas import PersonOut, TrackOut
from guildfm.auth import ActiveUser
from guildfm.db import get_session
from guildfm.models import (
    EntryState,
    Play,
    Playlist,
    PlaylistKind,
    PlaylistTrack,
    Station,
    StationKind,
)
from guildfm.playlists import covers, current_source, requests_only
from guildfm.queue import in_state

router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_session)]


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


class StationTileOut(BaseModel):
    id: int
    name: str
    kind: StationKind
    description: str
    dj_name: str | None  # None without a DJ
    global_awareness: bool
    art_url: str | None  # its cover, once OpenAI has painted one
    last_played_at: datetime | None
    filling: bool  # the station filling the gaps between requests
    on_air: bool  # the current song came from it


class NowOut(BaseModel):
    # Where the current song came from, if GuildFM put it on.
    on_air: Literal["queue", "library", "radio"] | None
    requests_only: bool  # someone chose to have nothing fill the gaps between requests
    playlists: list[PlaylistTileOut]  # last played first
    stations: list[StationTileOut]  # last played first


class PlayOut(BaseModel):
    id: int
    track: TrackOut
    played_at: datetime
    requested_by: PersonOut | None
    playlist: str | None
    station: str | None
    upvotes: int
    downvotes: int


class HistoryOut(BaseModel):
    plays: list[PlayOut]  # newest first
    more: bool  # earlier plays today, fetched with ?before=<the last play's id>


def _when(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, UTC)


@router.get("/now")
async def now(_: ActiveUser, db: Db) -> NowOut:
    source = await current_source(db)
    playing = await in_state(db, EntryState.PLAYING)
    on_air = None
    if playing:
        if playing.requested_by:
            on_air = "queue"
        elif playing.playlist_id:
            on_air = "library"
        elif playing.station_id:
            on_air = "radio"

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
    played = dict(
        (
            await db.execute(
                select(Play.station_id, func.max(Play.played_at))
                .where(Play.station_id.is_not(None))
                .group_by(Play.station_id)
            )
        ).all()
    )
    stations = (await db.scalars(select(Station))).unique().all()
    # Last played first. Ones that haven't played yet follow by name, with AI picks last.
    by_last = sorted(
        stations,
        key=lambda s: (-played.get(s.id, 0), s.kind == StationKind.AI_PICKS, s.name.lower()),
    )
    return NowOut(
        on_air=on_air,
        requests_only=await requests_only(db),
        playlists=[
            PlaylistTileOut(
                id=playlist.id,
                name=playlist.name,
                kind=playlist.kind,
                tracks=counts.get(playlist.id, 0),
                shuffle=playlist.shuffle,
                covers=await covers(db, playlist.id),
                last_played_at=_when(last[playlist.id]) if playlist.id in last else None,
                filling=bool(source and source.playlist_id == playlist.id),
                on_air=bool(playing and playing.playlist_id == playlist.id),
            )
            for playlist in ordered
        ],
        stations=[
            StationTileOut(
                id=station.id,
                name=station.name,
                kind=station.kind,
                description=station.description,
                dj_name=station.dj_name if station.dj else None,
                global_awareness=station.global_awareness,
                art_url=station.art_url,
                last_played_at=_when(played[station.id]) if station.id in played else None,
                filling=bool(source and source.station_id == station.id),
                on_air=bool(playing and playing.station_id == station.id),
            )
            for station in by_last
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
                requested_by=PersonOut.of(play.requester),
                playlist=play.playlist.name if play.playlist else None,
                station=play.station.name if play.station else None,
                upvotes=play.upvotes,
                downvotes=play.downvotes,
            )
            for play in plays[:limit]
        ],
        more=len(plays) > limit,
    )
