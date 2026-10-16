"""Playlists for curators: making, importing, editing and playing them. Also the playing
playlist's thumbs down, which anyone can give."""

import re
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.api.schemas import TrackOut
from guildfm.api.search import AlbumOut
from guildfm.auth import require
from guildfm.db import get_session
from guildfm.models import Playlist, PlaylistKind, PlaylistTrack, Track, User
from guildfm.permissions import Permission
from guildfm.playlists import add_track, covers, current_source, thumb_down, tracks_of
from guildfm.prefs import get_pref
from guildfm.queue import QueueEngine
from guildfm.spotify import SpotifyError, SpotifyNotFound, SpotifyTrack, remember

router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[User, require(Permission.SWITCH_SOURCE)]
Editor = Annotated[User, require(Permission.MANAGE_PLAYLISTS)]
Player = Annotated[User, require(Permission.SWITCH_SOURCE)]
Voter = Annotated[User, require(Permission.VOTE)]

_SPOTIFY_LINK = re.compile(
    r"(?:spotify:|open\.spotify\.com/(?:intl-[a-z-]+/)?)(playlist|album)[:/]([A-Za-z0-9]{22})"
)


def spotify_link(link: str) -> tuple[str, str] | None:
    """("playlist" or "album", its id) from a Spotify link or URI."""
    match = _SPOTIFY_LINK.search(link)
    return (match.group(1), match.group(2)) if match else None


class PlaylistOut(BaseModel):
    id: int
    name: str
    kind: PlaylistKind
    shuffle: bool
    tracks: int
    covers: list[str]  # album art from its first few songs
    made_by: str | None
    playing: bool


class PlaylistTrackOut(TrackOut):
    position: int
    upvotes: int


class PlaylistDetailOut(PlaylistOut):
    items: list[PlaylistTrackOut]


class AlbumDetailOut(AlbumOut):
    items: list[TrackOut]  # in order, leaving out any that can't play here or aren't allowed


def engine(request: Request) -> QueueEngine:
    return request.app.state.queue


async def _out(db: AsyncSession, playlist: Playlist) -> PlaylistOut:
    count = await db.scalar(
        select(func.count())
        .select_from(PlaylistTrack)
        .where(PlaylistTrack.playlist_id == playlist.id)
    )
    source = await current_source(db)
    return PlaylistOut(
        id=playlist.id,
        name=playlist.name,
        kind=playlist.kind,
        shuffle=playlist.shuffle,
        tracks=count or 0,
        covers=await covers(db, playlist.id),
        made_by=playlist.creator.display_name if playlist.creator else None,
        playing=bool(source and source.playlist_id == playlist.id),
    )


async def _detail(db: AsyncSession, playlist: Playlist) -> PlaylistDetailOut:
    items = [
        PlaylistTrackOut(
            **TrackOut.of(entry.track).model_dump(), position=entry.position, upvotes=entry.upvotes
        )
        for entry in await tracks_of(db, playlist.id)
    ]
    return PlaylistDetailOut(**(await _out(db, playlist)).model_dump(), items=items)


async def _playlist(db: AsyncSession, playlist_id: int) -> Playlist:
    playlist = await db.get(Playlist, playlist_id)
    if playlist is None:
        raise HTTPException(404, "That playlist doesn't exist any more.")
    return playlist


async def album_songs(
    db: AsyncSession, request: Request, album_id: str
) -> tuple[AlbumOut, list[SpotifyTrack]]:
    """An album and the songs on it GuildFM can play: explicit ones only if they're allowed."""
    try:
        album, tracks = await request.app.state.spotify.album(album_id)
    except SpotifyNotFound as error:
        raise HTTPException(404, str(error)) from None
    except SpotifyError as error:
        raise HTTPException(502, str(error)) from None
    await remember(db, tracks)
    if not await get_pref(db, "allow_explicit"):
        tracks = [track for track in tracks if not track.explicit]
    return AlbumOut.of(album), tracks


async def _track(db: AsyncSession, request: Request, track_id: str) -> Track:
    """A track by id, looked up on Spotify if GuildFM hasn't seen it before."""
    track = await db.get(Track, track_id)
    if track is None:
        try:
            found = await request.app.state.spotify.track(track_id)
        except SpotifyError as error:
            raise HTTPException(502, str(error)) from None
        if found is None:
            raise HTTPException(404, "Spotify doesn't have that track.")
        await remember(db, [found])
        track = await db.get(Track, track_id)
    return track


@router.get("/playlists")
async def playlists(_: Viewer, db: Db) -> list[PlaylistOut]:
    rows = (await db.scalars(select(Playlist))).unique().all()
    # Best Voted first, then by name.
    ordered = sorted(rows, key=lambda p: (p.kind != PlaylistKind.BEST_VOTED, p.name.lower()))
    return [await _out(db, playlist) for playlist in ordered]


class NewPlaylistIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.post("/playlists", status_code=201)
async def create(body: NewPlaylistIn, user: Editor, db: Db) -> PlaylistDetailOut:
    playlist = Playlist(
        name=body.name.strip(),
        kind=PlaylistKind.CUSTOM,
        created_by=user.id,
        created_at=time.time(),
    )
    db.add(playlist)
    await db.commit()
    return await _detail(db, playlist)


class ImportIn(BaseModel):
    link: str


@router.post("/playlists/import", status_code=201)
async def import_playlist(body: ImportIn, user: Editor, request: Request, db: Db):
    """A playlist from a Spotify playlist or album link. An album becomes a playlist named after
    it, in track order."""
    found = spotify_link(body.link)
    if found is None:
        raise HTTPException(422, "That isn't a Spotify playlist or album link.")
    kind, spotify_id = found
    if kind == "album":
        album, tracks = await album_songs(db, request, spotify_id)
        name = album.name
    else:
        try:
            name, tracks = await request.app.state.spotify.playlist(db, spotify_id)
        except SpotifyNotFound as error:
            raise HTTPException(404, str(error)) from None
        except SpotifyError as error:
            raise HTTPException(409, str(error)) from None
        await remember(db, tracks)
    playlist = Playlist(
        name=name[:100] or "Imported playlist",
        kind=PlaylistKind.IMPORTED,
        spotify_id=spotify_id,
        created_by=user.id,
        created_at=time.time(),
    )
    db.add(playlist)
    await db.flush()
    for track in tracks:
        await add_track(db, playlist, track.id)
    await db.commit()
    return await _detail(db, playlist)


@router.get("/playlists/{playlist_id}")
async def playlist(playlist_id: int, _: Viewer, db: Db) -> PlaylistDetailOut:
    return await _detail(db, await _playlist(db, playlist_id))


class PlaylistChangesIn(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    shuffle: bool | None = None


@router.patch("/playlists/{playlist_id}")
async def change(playlist_id: int, body: PlaylistChangesIn, _: Editor, db: Db) -> PlaylistDetailOut:
    playlist = await _playlist(db, playlist_id)
    if body.name is not None:
        if playlist.kind == PlaylistKind.BEST_VOTED:
            raise HTTPException(409, "Best Voted keeps its name.")
        playlist.name = body.name.strip()
    if body.shuffle is not None:
        playlist.shuffle = body.shuffle
    await db.commit()
    return await _detail(db, playlist)


@router.delete("/playlists/{playlist_id}", status_code=204)
async def delete(playlist_id: int, _: Editor, request: Request, db: Db) -> None:
    playlist = await _playlist(db, playlist_id)
    if playlist.kind == PlaylistKind.BEST_VOTED:
        raise HTTPException(409, "Best Voted can't be deleted.")
    await db.delete(playlist)
    await db.commit()
    await engine(request).changed()


class TrackIn(BaseModel):
    track_id: str = Field(pattern=r"^[A-Za-z0-9]{22}$")


@router.post("/playlists/{playlist_id}/tracks")
async def add(
    playlist_id: int, body: TrackIn, _: Editor, request: Request, db: Db
) -> PlaylistDetailOut:
    playlist = await _playlist(db, playlist_id)
    if playlist.kind == PlaylistKind.BEST_VOTED:
        raise HTTPException(409, "Best Voted fills itself from the votes.")
    track = await _track(db, request, body.track_id)
    if not await add_track(db, playlist, track.id):
        raise HTTPException(409, "That song is already in the playlist.")
    await db.commit()
    await engine(request).changed()
    return await _detail(db, playlist)


class AlbumIn(BaseModel):
    album_id: str = Field(pattern=r"^[A-Za-z0-9]{22}$")


@router.post("/playlists/{playlist_id}/albums")
async def add_album(
    playlist_id: int, body: AlbumIn, _: Editor, request: Request, db: Db
) -> PlaylistDetailOut:
    """Every song on an album, in order, after what's there. Songs already in it stay put."""
    playlist = await _playlist(db, playlist_id)
    if playlist.kind == PlaylistKind.BEST_VOTED:
        raise HTTPException(409, "Best Voted fills itself from the votes.")
    _, tracks = await album_songs(db, request, body.album_id)
    added = [await add_track(db, playlist, track.id) for track in tracks]
    if not any(added):
        raise HTTPException(409, "Every song on that album is already in the playlist.")
    await db.commit()
    await engine(request).changed()
    return await _detail(db, playlist)


@router.get("/albums/{album_id}")
async def album(album_id: str, _: Editor, request: Request, db: Db) -> AlbumDetailOut:
    """An album's songs, to look over before adding them to a playlist."""
    found, tracks = await album_songs(db, request, album_id)
    return AlbumDetailOut(**found.model_dump(), items=[TrackOut.of(track) for track in tracks])


@router.delete("/playlists/{playlist_id}/tracks/{track_id}")
async def remove(
    playlist_id: int, track_id: str, _: Editor, request: Request, db: Db
) -> PlaylistDetailOut:
    playlist = await _playlist(db, playlist_id)
    entry = await db.get(PlaylistTrack, (playlist.id, track_id))
    if entry:
        await db.delete(entry)
        await db.commit()
    await engine(request).changed()
    return await _detail(db, playlist)


# The playing playlist


@router.post("/playlists/{playlist_id}/play")
async def play(playlist_id: int, user: Player, request: Request, db: Db) -> PlaylistOut:
    """Make the playlist the one filling the gaps between requests, from the next song on."""
    playlist = await _playlist(db, playlist_id)
    if not await tracks_of(db, playlist.id):
        raise HTTPException(409, "That playlist is empty.")
    if await engine(request).switch(playlist):
        engine(request).note(f"{user.display_name} put {playlist.name} on")
    # If GuildFM opened with nothing to play, this starts the playlist.
    await request.app.state.schedule.try_start()
    return await _out(db, playlist)


@router.delete("/source", status_code=204)
async def stop(user: Player, request: Request, db: Db) -> None:
    """Requests only: after the current song, nothing fills the gaps between requests, and
    nothing takes over when the queue runs out."""
    source = await current_source(db)
    name = source and (source.playlist or source.station).name
    if await engine(request).switch(None):
        what = f"took {name} off" if name else "chose requests only"
        engine(request).note(f"{user.display_name} {what}")


class ThumbIn(BaseModel):
    track_id: str
    down: bool  # false takes the thumbs down back


@router.post("/source/vote")
async def thumb(body: ThumbIn, user: Voter, request: Request, db: Db) -> dict:
    """A thumbs down on one of the playlist's or station's upcoming songs."""
    async with engine(request).lock:
        if await current_source(db) is None:
            raise HTTPException(409, "Nothing is filling the gaps between requests.")
        threshold = await get_pref(db, "downvote_threshold")
        skipped = await thumb_down(db, body.track_id, user.id, body.down, threshold)
    if skipped:
        track = await db.get(Track, body.track_id)
        engine(request).note(
            f"{track.title if track else 'A song'} will be skipped this time round"
        )
    await engine(request).changed()
    return {"skipped": skipped}
