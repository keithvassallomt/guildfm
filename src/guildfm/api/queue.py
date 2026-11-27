"""The request queue: what's on, what's next, and what everyone is voting on."""

import time
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm import kiosk
from guildfm.api.playlists import AlbumIn, album_songs
from guildfm.api.schemas import PersonOut, TrackOut
from guildfm.auth import ActiveUser, require
from guildfm.db import get_session
from guildfm.models import EntryState, PlaylistTrack, QueueEntry, Role, Track, User, Vote
from guildfm.permissions import Permission, can
from guildfm.playlists import best_voted, current_source, tracks_of
from guildfm.playlists import upcoming as upcoming_songs
from guildfm.prefs import get_pref
from guildfm.queue import QueueEngine, Tally, in_order, recent_plays, tallies, waiting
from guildfm.spotify import SpotifyError, remember

router = APIRouter(prefix="/queue")
Db = Annotated[AsyncSession, Depends(get_session)]
Requester = Annotated[User, require(Permission.ADD_TRACKS)]
Voter = Annotated[User, require(Permission.VOTE)]
Curator = Annotated[User, require(Permission.MANAGE_QUEUE)]


class EntryOut(BaseModel):
    id: int
    state: EntryState
    track: TrackOut
    requested_by: PersonOut | None  # None for songs from the playlist or station
    playlist: str | None  # the playlist a song came from, if it did
    station: str | None  # the station a song came from, if it did
    requested_at: datetime
    up: int
    down: int
    score: int
    my_vote: int  # -1, 0 or 1
    mine: bool
    pinned: bool  # placed by a curator, so votes don't move it
    played_at: datetime | None  # when it last played before this request, if recently
    album: str | None  # the album's name, for a song queued with the rest of its album
    # For the kiosk: its own thumbs on the song, and until when it can take its request back.
    kiosk_up: int = 0
    kiosk_down: int = 0
    undo_until: datetime | None = None
    # For the song that's playing: when it joined Best Voted, if it's in it.
    best_voted_at: datetime | None = None


class KioskOut(BaseModel):
    places: int
    used: int
    break_until: datetime | None  # while it's on a break
    break_seconds: int  # how long a break lasts
    votes: int  # the most it counts for each way on a song
    undo_seconds: int
    theme: Literal["dark", "light"]
    now: datetime  # the server's time, so the screen's countdowns don't rely on its own clock


class ActivityOut(BaseModel):
    text: str
    at: datetime


class UpcomingOut(BaseModel):
    track: TrackOut
    down: int  # thumbs down so far
    my_down: bool


class SourceOut(BaseModel):
    kind: Literal["playlist", "station"]
    id: int
    name: str
    upcoming: list[UpcomingOut]
    skip_at: int  # thumbs down needed to skip a song


class QueueOut(BaseModel):
    playing: EntryOut | None
    next: EntryOut | None
    waiting: list[EntryOut]
    source: SourceOut | None  # the playlist or station filling the gaps between requests
    activity: list[ActivityOut]
    mine: int  # how many requests the viewer has in the queue
    request_cap: int
    kiosk: KioskOut | None = None  # where the kiosk stands, when the viewer is one


def engine(request: Request) -> QueueEngine:
    return request.app.state.queue


def _when(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, UTC)


async def view(db: AsyncSession, viewer: User, queue: QueueEngine) -> QueueOut:
    entries = list((await db.scalars(select(QueueEntry))).unique().all())
    ids = [entry.id for entry in entries]
    scores = await tallies(db, ids)
    my_votes = dict(
        (await db.execute(select(Vote.entry_id, Vote.value).where(Vote.user_id == viewer.id))).all()
    )
    now = time.time()
    since = now - await get_pref(db, "recently_played_hours") * 3600
    plays = await recent_plays(db, since, [entry.track_id for entry in entries])
    is_kiosk = kiosk.is_kiosk(viewer)
    kiosk_votes = await kiosk.votes_of(db, viewer) if is_kiosk else {}
    playing = next((entry for entry in entries if entry.state == EntryState.PLAYING), None)
    joined = playing and await db.get(PlaylistTrack, ((await best_voted(db)).id, playing.track_id))

    def undo_until(entry: QueueEntry) -> datetime | None:
        until = entry.added_at + kiosk.UNDO_SECONDS
        fresh = entry.state == EntryState.WAITING and now < until
        return _when(until) if is_kiosk and entry.requested_by == viewer.id and fresh else None

    def out(entry: QueueEntry) -> EntryOut:
        tally = scores.get(entry.id, Tally())
        before = [at for at in plays.get(entry.track_id, []) if at < entry.added_at]
        thumbs = kiosk_votes.get(entry.id, (0, 0))
        return EntryOut(
            id=entry.id,
            state=entry.state,
            track=TrackOut.of(entry.track),
            requested_by=PersonOut.of(entry.requester),
            playlist=entry.playlist.name if entry.playlist else None,
            station=entry.station.name if entry.station else None,
            requested_at=_when(entry.added_at),
            up=tally.up,
            down=tally.down,
            score=tally.score,
            my_vote=my_votes.get(entry.id, 0),
            mine=entry.requested_by == viewer.id,
            pinned=entry.pinned_position is not None,
            played_at=_when(before[-1]) if before else None,
            album=entry.track.album if entry.album_id else None,
            kiosk_up=thumbs[0],
            kiosk_down=thumbs[1],
            undo_until=undo_until(entry),
            best_voted_at=_when(joined.added_at) if joined and entry is playing else None,
        )

    by_state = {state: [e for e in entries if e.state == state] for state in EntryState}
    source = await current_source(db)
    source_out = None
    if source:
        upcoming = await upcoming_songs(db, {entry.track_id for entry in entries})
        found = {t.id: t for t in await db.scalars(select(Track).where(Track.id.in_(upcoming)))}
        source_out = SourceOut(
            kind="playlist" if source.playlist else "station",
            id=source.playlist_id or source.station_id,
            name=(source.playlist or source.station).name,
            upcoming=[
                UpcomingOut(
                    track=TrackOut.of(found[track_id]),
                    down=len(source.downvotes.get(track_id, [])),
                    my_down=viewer.id in source.downvotes.get(track_id, []),
                )
                for track_id in upcoming
                if track_id in found
            ],
            skip_at=-(await get_pref(db, "downvote_threshold")),
        )
    kiosk_out = None
    if is_kiosk:
        state = await kiosk.places(db, viewer, now)
        await db.commit()  # a break that's over ends here
        kiosk_out = KioskOut(
            places=state.total,
            used=state.used,
            break_until=_when(state.break_until) if state.break_until else None,
            break_seconds=await get_pref(db, "kiosk_break_minutes") * 60,
            votes=kiosk.VOTES,
            undo_seconds=kiosk.UNDO_SECONDS,
            theme=await get_pref(db, "kiosk_theme"),
            now=_when(now),
        )
    return QueueOut(
        playing=next(map(out, by_state[EntryState.PLAYING]), None),
        next=next(map(out, by_state[EntryState.NEXT]), None),
        waiting=[out(entry) for entry in in_order(by_state[EntryState.WAITING], scores)],
        source=source_out,
        activity=[ActivityOut(text=a["text"], at=_when(a["at"])) for a in queue.activity],
        mine=sum(entry.requested_by == viewer.id and not entry.album_id for entry in entries),
        request_cap=await get_pref(db, "request_cap"),
        kiosk=kiosk_out,
    )


async def waiting_entry(db: AsyncSession, entry_id: int) -> QueueEntry:
    entry = await db.get(QueueEntry, entry_id)
    if entry is None:
        raise HTTPException(404, "That request isn't in the queue any more.")
    if entry.state != EntryState.WAITING:
        raise HTTPException(409, "That one's already on its way to the speakers.")
    return entry


@router.get("")
async def queue(viewer: ActiveUser, request: Request, db: Db) -> QueueOut:
    return await view(db, viewer, engine(request))


class RequestIn(BaseModel):
    track_id: str = Field(pattern=r"^[A-Za-z0-9]{22}$")


@router.post("", status_code=201)
async def add(body: RequestIn, user: Requester, request: Request, db: Db) -> QueueOut:
    queue = engine(request)
    track = await db.get(Track, body.track_id)
    if track is None:
        try:
            found = await request.app.state.spotify.track(body.track_id)
        except SpotifyError as error:
            raise HTTPException(502, str(error)) from None
        if found is None:
            raise HTTPException(404, "Spotify doesn't have that track.")
        await remember(db, [found])
        track = await db.get(Track, body.track_id)
    if track.explicit and not await get_pref(db, "allow_explicit"):
        raise HTTPException(403, "Explicit tracks are turned off.")

    at_kiosk = kiosk.is_kiosk(user)
    async with queue.lock:
        if await db.scalar(select(QueueEntry.id).where(QueueEntry.track_id == track.id)):
            raise HTTPException(409, "That song is already in the queue.")
        now = time.time()
        if at_kiosk:
            # The kiosk has places and breaks instead of a cap.
            await kiosk.check_room(db, user, now)
        else:
            cap = await get_pref(db, "request_cap")
            # Songs queued with the rest of their album don't count.
            mine = await db.scalar(
                select(func.count())
                .select_from(QueueEntry)
                .where(QueueEntry.requested_by == user.id, QueueEntry.album_id.is_(None))
            )
            # Admins have no cap.
            if mine >= cap and user.role != Role.ADMIN:
                raise HTTPException(
                    409,
                    f"You have {cap} requests in the queue already. Add more once one has played.",
                )
        db.add(QueueEntry(track_id=track.id, requested_by=user.id, added_at=now))
        try:
            await db.commit()
        except IntegrityError:
            raise HTTPException(409, "That song is already in the queue.") from None
        if at_kiosk:
            await kiosk.after_request(db, user, now)

    queue.note(
        f"Someone at the kiosk requested {track.title}"
        if at_kiosk
        else f"{user.display_name} requested {track.title}"
    )
    await queue.changed()
    # If the speakers had run out of things to play, or GuildFM opened with nothing to play,
    # this starts the new request.
    await queue.keep_fed()
    await request.app.state.schedule.try_start()
    return await view(db, user, queue)


class FavouriteOut(BaseModel):
    track: TrackOut
    queued: bool  # already in the queue, so it can't be requested again
    playing: bool


FAVOURITES = 30


@router.get("/favourites")
async def favourites(_: Requester, db: Db) -> list[FavouriteOut]:
    """The office's favourites, from Best Voted, most thumbs up first: the songs the kiosk offers
    before anyone searches."""
    allow_explicit = await get_pref(db, "allow_explicit")
    songs = sorted(
        await tracks_of(db, (await best_voted(db)).id),
        key=lambda song: (-song.upvotes, -song.added_at),
    )
    states = dict((await db.execute(select(QueueEntry.track_id, QueueEntry.state))).all())
    return [
        FavouriteOut(
            track=TrackOut.of(song.track),
            queued=song.track_id in states,
            playing=states.get(song.track_id) == EntryState.PLAYING,
        )
        for song in songs
        if allow_explicit or not song.track.explicit
    ][:FAVOURITES]


class AlbumQueuedOut(BaseModel):
    queue: QueueOut
    added: int  # songs added; any already in the queue are left where they are


@router.post("/albums", status_code=201)
async def add_album(body: AlbumIn, user: Curator, request: Request, db: Db) -> AlbumQueuedOut:
    """Every song on an album, in order, as the curator's requests. They don't count towards
    the request cap, and votes move them like any other request."""
    queue = engine(request)
    album, tracks = await album_songs(db, request, body.album_id)
    if not tracks:
        raise HTTPException(409, "None of that album's songs can play here.")
    async with queue.lock:
        queued = set(await db.scalars(select(QueueEntry.track_id)))
        adding = [track for track in tracks if track.id not in queued]
        if not adding:
            raise HTTPException(409, "Every song on that album is already in the queue.")
        now = time.time()
        for number, track in enumerate(adding):
            # A moment apart, so with equal votes they play in the album's order.
            db.add(
                QueueEntry(
                    track_id=track.id,
                    requested_by=user.id,
                    added_at=now + number / 1000,
                    album_id=body.album_id,
                )
            )
        try:
            await db.commit()
        except IntegrityError:
            raise HTTPException(409, "One of those songs was added just now. Try again.") from None

    songs = f"{len(adding)} {'song' if len(adding) == 1 else 'songs'}"
    queue.note(f"{user.display_name} queued {album.name} by {album.artists} ({songs})")
    await queue.changed()
    await queue.keep_fed()
    await request.app.state.schedule.try_start()
    return AlbumQueuedOut(queue=await view(db, user, queue), added=len(adding))


class VoteIn(BaseModel):
    value: Literal[-1, 0, 1]  # 0 takes your vote back


@router.post("/{entry_id}/vote")
async def vote(entry_id: int, body: VoteIn, user: Voter, request: Request, db: Db) -> QueueOut:
    """A vote on a waiting request, or on the song that's playing. Enough thumbs down take a
    request out of the queue, but nothing stops the song that's playing: its votes are kept with
    its play. The song locked in to play next can't be voted on."""
    queue = engine(request)
    async with queue.lock:
        entry = await db.get(QueueEntry, entry_id)
        playing = entry is not None and entry.state == EntryState.PLAYING
        if not playing:
            entry = await waiting_entry(db, entry_id)
        title = entry.track.title
        at_kiosk = kiosk.is_kiosk(user)
        if at_kiosk:
            # Each tap at the kiosk is another vote, up to kiosk.VOTES each way.
            await kiosk.check_not_on_break(db, user, time.time())
            await kiosk.vote(db, user, entry_id, body.value)
            thumbs_up = body.value == 1
        else:
            existing = await db.get(Vote, (entry_id, user.id))
            thumbs_up = body.value == 1 and (existing is None or existing.value != 1)
            if body.value == 0:
                if existing:
                    await db.delete(existing)
            else:
                await db.merge(Vote(entry_id=entry_id, user_id=user.id, value=body.value))
        await db.commit()

        joined = removed = False
        if playing:
            joined = await queue.count_votes_on_playing(db, entry)
        else:
            tally = (await tallies(db, [entry_id])).get(entry_id, Tally())
            removed = tally.score <= await get_pref(db, "downvote_threshold")
        if removed:
            await db.delete(entry)
            await db.commit()

    if removed:
        queue.note(f"{title} was removed after too many thumbs down")
    elif thumbs_up:
        who = "Someone at the kiosk" if at_kiosk else user.display_name
        queue.note(f"{who} gave {title} a thumbs up")
    if joined:
        queue.note(f"{title} made it into Best Voted")
    await queue.changed()
    return await view(db, user, queue)


@router.delete("/{entry_id}")
async def remove(entry_id: int, user: ActiveUser, request: Request, db: Db) -> QueueOut:
    queue = engine(request)
    async with queue.lock:
        entry = await db.get(QueueEntry, entry_id)
        if entry is None:
            raise HTTPException(404, "That request isn't in the queue any more.")
        own = entry.requested_by == user.id
        at_kiosk = kiosk.is_kiosk(user)
        if at_kiosk:
            # The kiosk can only take its own request back, just after adding it.
            if not own:
                raise HTTPException(403, "You can only remove your own requests.")
            kiosk.check_undo(entry, time.time())
        else:
            allowed = Permission.REMOVE_OWN_TRACKS if own else Permission.MANAGE_QUEUE
            if not can(user.role, allowed):
                raise HTTPException(403, "You can only remove your own requests.")
        entry = await waiting_entry(db, entry_id)
        title = entry.track.title
        await db.delete(entry)
        if at_kiosk:
            # That gives a place back, so taking back the request that started a break ends it.
            user.kiosk_break_until = None
        await db.commit()

    if at_kiosk:
        queue.note(f"Someone at the kiosk took {title} back")
    else:
        queue.note(
            f"{user.display_name} removed {title}"
            if own
            else f"{user.display_name} took {title} out of the queue"
        )
    await queue.changed()
    return await view(db, user, queue)


class MoveIn(BaseModel):
    position: int = Field(ge=1)  # where in the waiting requests to put it, from 1


@router.post("/{entry_id}/move")
async def move(entry_id: int, body: MoveIn, user: Curator, request: Request, db: Db) -> QueueOut:
    """Put a request at `position`, overriding the votes. It stays where it's put."""
    queue = engine(request)
    async with queue.lock:
        entry = await waiting_entry(db, entry_id)
        order = (await waiting(db))[0]
        before = order.index(entry) + 1
        order.remove(entry)
        order.insert(min(body.position, len(order) + 1) - 1, entry)
        # Pin the moved request, and re-pin any a curator had placed before, at their new
        # places. Requests nobody placed keep following the votes in the gaps between.
        for index, placed in enumerate(order, start=1):
            if placed is entry or placed.pinned_position is not None:
                placed.pinned_position = index
        await db.commit()
        title, after = entry.track.title, order.index(entry) + 1

    if after != before:
        queue.note(f"{user.display_name} moved {title} {'up' if after < before else 'down'}")
    await queue.changed()
    return await view(db, user, queue)
