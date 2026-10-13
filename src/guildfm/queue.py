"""The request queue: who asked for what, the votes, and keeping the speakers fed from it.

Requests wait in the vote. Shortly before the current song ends, the one at the top is handed
to the speakers and locked in as "next"; when the speakers move on to it, it becomes "playing"
and goes into the play history.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from guildfm.live import LiveHub
from guildfm.models import EntryState, Play, QueueEntry, Vote
from guildfm.playback import PlaybackController, Status
from guildfm.speakers import QueueItem, SpeakersRefused, SpeakersUnavailable, spotify_item
from guildfm.speakers import spotify_track_id as track_id_in

log = logging.getLogger(__name__)

LEAD_SECONDS = 30  # how long before a song ends the next request goes to the speakers
ACTIVITY_KEPT = 30


@dataclass(frozen=True)
class Tally:
    up: int = 0
    down: int = 0

    @property
    def score(self) -> int:
        return self.up - self.down


async def tallies(db: AsyncSession, entry_ids: Sequence[int]) -> dict[int, Tally]:
    if not entry_ids:
        return {}
    rows = await db.execute(
        select(
            Vote.entry_id,
            func.sum(case((Vote.value > 0, 1), else_=0)),
            func.sum(case((Vote.value < 0, 1), else_=0)),
        )
        .where(Vote.entry_id.in_(entry_ids))
        .group_by(Vote.entry_id)
    )
    return {entry_id: Tally(up, down) for entry_id, up, down in rows}


def in_order(entries: Sequence[QueueEntry], scores: dict[int, Tally]) -> list[QueueEntry]:
    """Highest score first, earliest request first on a tie. Entries a curator placed keep
    their position whatever the votes say."""
    free = sorted(
        (entry for entry in entries if entry.pinned_position is None),
        key=lambda entry: (-scores.get(entry.id, Tally()).score, entry.added_at, entry.id),
    )
    pinned = sorted(
        (entry for entry in entries if entry.pinned_position is not None),
        key=lambda entry: (entry.pinned_position, entry.added_at),
    )
    for entry in pinned:
        free.insert(min(entry.pinned_position - 1, len(free)), entry)
    return free


async def waiting(db: AsyncSession) -> tuple[list[QueueEntry], dict[int, Tally]]:
    entries = list(
        (await db.scalars(select(QueueEntry).where(QueueEntry.state == EntryState.WAITING)))
        .unique()
        .all()
    )
    scores = await tallies(db, [entry.id for entry in entries])
    return in_order(entries, scores), scores


async def in_state(db: AsyncSession, state: EntryState) -> QueueEntry | None:
    return (await db.scalars(select(QueueEntry).where(QueueEntry.state == state))).unique().first()


class QueueEngine:
    def __init__(
        self,
        sessionmaker: Callable[[], AsyncSession] | async_sessionmaker,
        controller: PlaybackController,
        hub: LiveHub,
        *,
        sid: int,
        sn: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._sessions = sessionmaker
        self._controller = controller
        self._hub = hub
        self._sid = sid
        self._sn = sn
        self._clock = clock
        # Serialises changes to the queue, so a vote and a hand-over to the speakers can't
        # interleave. The API takes it too.
        self.lock = asyncio.Lock()
        self.activity: deque[dict] = deque(maxlen=ACTIVITY_KEPT)

        controller.on_track_change.append(self._track_changed)
        controller.on_poll.append(self.keep_fed)
        controller.source = self._first_up

    def item(self, entry: QueueEntry) -> QueueItem:
        return spotify_item(entry.track_id, sid=self._sid, sn=self._sn)

    async def changed(self) -> None:
        """Tell every browser to fetch the queue again (each sees its own votes)."""
        await self._hub.broadcast("queue", {})

    def note(self, text: str) -> None:
        self.activity.appendleft({"text": text, "at": self._clock()})

    async def recover(self) -> None:
        """After a restart GuildFM isn't driving the speakers, so nothing is locked in."""
        async with self._sessions() as db:
            await db.execute(delete(QueueEntry).where(QueueEntry.state == EntryState.PLAYING))
            await db.execute(
                update(QueueEntry)
                .where(QueueEntry.state == EntryState.NEXT)
                .values(state=EntryState.WAITING, pinned_position=1)
            )
            await db.commit()

    async def _lock_head(self, db: AsyncSession) -> QueueEntry | None:
        """Take the top request out of the vote and mark it as next. Placed entries move up."""
        entries, _ = await waiting(db)
        if not entries:
            return None
        head = entries[0]
        head.state = EntryState.NEXT
        head.pinned_position = None
        for entry in entries[1:]:
            if entry.pinned_position is not None:
                entry.pinned_position = max(1, entry.pinned_position - 1)
        await db.commit()
        return head

    async def _unlock(self, entry_id: int) -> None:
        async with self._sessions() as db:
            entry = await db.get(QueueEntry, entry_id)
            if entry and entry.state == EntryState.NEXT:
                entry.state, entry.pinned_position = EntryState.WAITING, 1
                await db.commit()

    async def keep_fed(self) -> None:
        """After each reading of the speakers: line up the next request when the current song
        is nearly over, or start one if the queue had run dry."""
        controller = self._controller
        if not controller.in_control:
            return
        status, left = controller.status, controller.time_left
        if status == Status.PLAYING and left is not None and left > LEAD_SECONDS:
            return
        if status not in (Status.PLAYING, Status.IDLE):
            return
        async with self.lock, self._sessions() as db:
            if await in_state(db, EntryState.NEXT):
                return
            head = await self._lock_head(db)
            if head is None:
                return
            entry_id, item = head.id, self.item(head)
        try:
            if status == Status.IDLE:
                await controller.play_now(item)
            else:
                await controller.queue_next(item)
        except SpeakersUnavailable, SpeakersRefused:
            log.warning("Couldn't hand the next request to the speakers", exc_info=True)
            await self._unlock(entry_id)
        await self.changed()

    async def skip(self) -> None:
        """Skip the current song, lining up the next request first so the music carries on."""
        controller = self._controller
        item = None
        if controller.in_control:
            async with self.lock, self._sessions() as db:
                if not await in_state(db, EntryState.NEXT):
                    head = await self._lock_head(db)
                    item = head and self.item(head)
        if item:
            await controller.queue_next(item)
        await controller.skip()
        await self.changed()

    async def _first_up(self) -> list[QueueItem]:
        """What to play when GuildFM takes the speakers over and has nothing lined up."""
        async with self.lock, self._sessions() as db:
            head = await in_state(db, EntryState.NEXT) or await self._lock_head(db)
            return [self.item(head)] if head else []

    async def _track_changed(self, before: str | None, after: str | None) -> None:
        """The speakers moved on: the song that finished leaves the queue, the next one plays."""
        finished, started = track_id_in(before), track_id_in(after)
        async with self._sessions() as db:
            playing = await in_state(db, EntryState.PLAYING)
            if playing and playing.track_id != started:
                await db.delete(playing)
            entry = None
            if started:
                entry = (
                    (await db.scalars(select(QueueEntry).where(QueueEntry.track_id == started)))
                    .unique()
                    .first()
                )
            if entry and entry.state != EntryState.PLAYING:
                tally = (await tallies(db, [entry.id])).get(entry.id, Tally())
                entry.state, entry.pinned_position = EntryState.PLAYING, None
                db.add(
                    Play(
                        track_id=entry.track_id,
                        requested_by=entry.requested_by,
                        played_at=self._clock(),
                        upvotes=tally.up,
                        downvotes=tally.down,
                    )
                )
                self.note(
                    f"Now playing {entry.track.title}, requested by {entry.requester.display_name}"
                )
            await db.commit()
        if finished or started:
            await self.changed()


async def recent_plays(
    db: AsyncSession, since: float, track_ids: Sequence[str]
) -> dict[str, list[float]]:
    """When each of `track_ids` was played since `since`, oldest first."""
    if not track_ids:
        return {}
    rows = await db.execute(
        select(Play.track_id, Play.played_at)
        .where(Play.track_id.in_(track_ids), Play.played_at >= since)
        .order_by(Play.played_at)
    )
    plays: dict[str, list[float]] = {}
    for track_id, played_at in rows:
        plays.setdefault(track_id, []).append(played_at)
    return plays
