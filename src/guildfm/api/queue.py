"""The request queue: what's on, what's next, and what everyone is voting on."""

import time
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.api.schemas import TrackOut
from guildfm.auth import ActiveUser, require
from guildfm.db import get_session
from guildfm.models import EntryState, QueueEntry, Track, User, Vote
from guildfm.permissions import Permission, can
from guildfm.prefs import get_pref
from guildfm.queue import QueueEngine, Tally, in_order, recent_plays, tallies, waiting
from guildfm.spotify import SpotifyError, remember

router = APIRouter(prefix="/queue")
Db = Annotated[AsyncSession, Depends(get_session)]
Requester = Annotated[User, require(Permission.ADD_TRACKS)]
Voter = Annotated[User, require(Permission.VOTE)]
Curator = Annotated[User, require(Permission.MANAGE_QUEUE)]


class PersonOut(BaseModel):
    id: int
    display_name: str


class EntryOut(BaseModel):
    id: int
    state: EntryState
    track: TrackOut
    requested_by: PersonOut
    requested_at: datetime
    up: int
    down: int
    score: int
    my_vote: int  # -1, 0 or 1
    mine: bool
    pinned: bool  # placed by a curator, so votes don't move it
    played_at: datetime | None  # when it last played before this request, if recently


class ActivityOut(BaseModel):
    text: str
    at: datetime


class QueueOut(BaseModel):
    playing: EntryOut | None
    next: EntryOut | None
    waiting: list[EntryOut]
    activity: list[ActivityOut]
    mine: int  # how many requests the viewer has in the queue
    request_cap: int


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
    since = time.time() - await get_pref(db, "recently_played_hours") * 3600
    plays = await recent_plays(db, since, [entry.track_id for entry in entries])

    def out(entry: QueueEntry) -> EntryOut:
        tally = scores.get(entry.id, Tally())
        before = [at for at in plays.get(entry.track_id, []) if at < entry.added_at]
        return EntryOut(
            id=entry.id,
            state=entry.state,
            track=TrackOut.of(entry.track),
            requested_by=PersonOut(
                id=entry.requester.id, display_name=entry.requester.display_name
            ),
            requested_at=_when(entry.added_at),
            up=tally.up,
            down=tally.down,
            score=tally.score,
            my_vote=my_votes.get(entry.id, 0),
            mine=entry.requested_by == viewer.id,
            pinned=entry.pinned_position is not None,
            played_at=_when(before[-1]) if before else None,
        )

    by_state = {state: [e for e in entries if e.state == state] for state in EntryState}
    return QueueOut(
        playing=next(map(out, by_state[EntryState.PLAYING]), None),
        next=next(map(out, by_state[EntryState.NEXT]), None),
        waiting=[out(entry) for entry in in_order(by_state[EntryState.WAITING], scores)],
        activity=[ActivityOut(text=a["text"], at=_when(a["at"])) for a in queue.activity],
        mine=sum(entry.requested_by == viewer.id for entry in entries),
        request_cap=await get_pref(db, "request_cap"),
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

    async with queue.lock:
        if await db.scalar(select(QueueEntry.id).where(QueueEntry.track_id == track.id)):
            raise HTTPException(409, "That song is already in the queue.")
        cap = await get_pref(db, "request_cap")
        mine = await db.scalar(
            select(func.count()).select_from(QueueEntry).where(QueueEntry.requested_by == user.id)
        )
        if mine >= cap:
            raise HTTPException(
                409, f"You have {cap} requests in the queue already. Add more once one has played."
            )
        db.add(QueueEntry(track_id=track.id, requested_by=user.id, added_at=time.time()))
        try:
            await db.commit()
        except IntegrityError:
            raise HTTPException(409, "That song is already in the queue.") from None

    queue.note(f"{user.display_name} requested {track.title}")
    await queue.changed()
    # If the speakers had run out of things to play, this starts the new request.
    await queue.keep_fed()
    return await view(db, user, queue)


class VoteIn(BaseModel):
    value: Literal[-1, 0, 1]  # 0 takes your vote back


@router.post("/{entry_id}/vote")
async def vote(entry_id: int, body: VoteIn, user: Voter, request: Request, db: Db) -> QueueOut:
    queue = engine(request)
    async with queue.lock:
        entry = await waiting_entry(db, entry_id)
        title = entry.track.title
        existing = await db.get(Vote, (entry_id, user.id))
        thumbs_up = body.value == 1 and (existing is None or existing.value != 1)
        if body.value == 0:
            if existing:
                await db.delete(existing)
        else:
            await db.merge(Vote(entry_id=entry_id, user_id=user.id, value=body.value))
        await db.commit()

        tally = (await tallies(db, [entry_id])).get(entry_id, Tally())
        removed = tally.score <= await get_pref(db, "downvote_threshold")
        if removed:
            await db.delete(entry)
            await db.commit()

    if removed:
        queue.note(f"{title} was removed after too many thumbs down")
    elif thumbs_up:
        queue.note(f"{user.display_name} gave {title} a thumbs up")
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
        allowed = Permission.REMOVE_OWN_TRACKS if own else Permission.MANAGE_QUEUE
        if not can(user.role, allowed):
            raise HTTPException(403, "You can only remove your own requests.")
        entry = await waiting_entry(db, entry_id)
        title = entry.track.title
        await db.delete(entry)
        await db.commit()

    queue.note(
        f"{user.display_name} removed {title}"
        if own
        else f"{user.display_name} took {title} out of the queue"
    )
    await queue.changed()
    return await view(db, user, queue)


class MoveIn(BaseModel):
    direction: Literal["up", "down"]


@router.post("/{entry_id}/move")
async def move(entry_id: int, body: MoveIn, user: Curator, request: Request, db: Db) -> QueueOut:
    """Move a request one place, overriding the votes. It stays where it's put."""
    queue = engine(request)
    async with queue.lock:
        entry = await waiting_entry(db, entry_id)
        order = [e.id for e in (await waiting(db))[0]]
        index = order.index(entry.id)
        target = index - 1 if body.direction == "up" else index + 1
        if 0 <= target < len(order):
            neighbour = await db.get(QueueEntry, order[target])
            if neighbour.pinned_position is not None:
                neighbour.pinned_position = index + 1
            entry.pinned_position = target + 1
            await db.commit()
        title = entry.track.title

    queue.note(f"{user.display_name} moved {title} {body.direction}")
    await queue.changed()
    return await view(db, user, queue)
