"""The request queue: who asked for what, the votes, and keeping the speakers fed from it.

Requests wait in the vote. Shortly before the current song ends, the one at the top is handed
to the speakers and locked in as "next"; when the speakers move on to it, it becomes "playing"
and goes into the play history.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from guildfm.lineups import Change, Opening, follow, gap_station, minute_of, put_on
from guildfm.live import LiveHub
from guildfm.models import (
    EntryState,
    Lineup,
    Play,
    Playlist,
    QueueEntry,
    SourceState,
    Station,
    Vote,
)
from guildfm.playback import PlaybackController, Status
from guildfm.playlists import (
    best_voted,
    choose_requests_only,
    consider_for_best_voted,
    current_source,
    give_back,
    play_playlist,
    play_station,
    requests_only,
    take_next,
)
from guildfm.prefs import get_pref
from guildfm.radio import Radio, ai_picks
from guildfm.speakers import QueueItem, SpeakersRefused, SpeakersUnavailable, spotify_item
from guildfm.speakers import spotify_track_id as track_id_in

log = logging.getLogger(__name__)

# How long before a song ends the next request goes to the speakers. The DJ's line for it takes
# up to half a minute to make, and lines that went into the Sonos queue in a song's last few
# seconds often left the speakers stopped after them.
LEAD_SECONDS = 90
# Readings of stopped speakers with a song lined up before GuildFM tries it again, and after a
# second try, gives up on it: it couldn't play.
STALLED_READINGS = 3
PREPARE_MINUTES = 10  # how soon before a line-up's show its station picks its first songs
ACTIVITY_KEPT = 30

# What fills the gaps between requests: a playlist, a station, a line-up, or nothing
# ("requests only").
Choice = Playlist | Station | Lineup | None
# Told the entry, its track key, and when a song opens a line-up's show, the minute the show ends.
LinedUp = Callable[[int, str, int | None], Awaitable[None]]


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
        radio: Radio | None = None,
        clock: Callable[[], float] = time.time,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessionmaker
        self._controller = controller
        self._hub = hub
        self._radio = radio
        self._sid = sid
        self._sn = sn
        self._clock = clock
        self._now = now  # the time of day, for line-ups
        # A line-up's show that has started, waiting for its first song: its station and end.
        self._opening: Opening | None = None
        # That first song's entry, and the minute its show ends.
        self._opener: tuple[int, int] | None = None
        self._stalls = 0  # readings of stopped speakers with a song lined up
        self._retried: int | None = None  # the lined-up entry the speakers were asked to retry
        # Serialises changes to the queue, so a vote and a hand-over to the speakers can't
        # interleave. The API takes it too.
        self.lock = asyncio.Lock()
        self.activity: deque[dict] = deque(maxlen=ACTIVITY_KEPT)
        # Told the entry and its track key when the next song is handed to the speakers ahead
        # of time, so the DJ can get a line ready.
        self.on_lined_up: list[LinedUp] = []

        controller.on_track_change.append(self._track_changed)
        controller.on_poll.append(self.keep_fed)
        controller.source = self._first_up

    def item(self, entry: QueueEntry) -> QueueItem:
        seconds = entry.track.duration_ms / 1000
        return spotify_item(entry.track_id, sid=self._sid, sn=self._sn, seconds=seconds)

    async def changed(self) -> None:
        """Tell every browser to fetch the queue again (each sees its own votes)."""
        await self._hub.broadcast("queue", {})

    def note(self, text: str) -> None:
        self.activity.appendleft({"text": text, "at": self._clock()})

    async def office_time(self, db: AsyncSession, ahead: float = 0) -> datetime:
        """The time in the office, `ahead` seconds from now."""
        zone = ZoneInfo(await get_pref(db, "timezone"))
        return (self._now() + timedelta(seconds=ahead)).astimezone(zone)

    async def _follow(self, db: AsyncSession, ahead: float = 0) -> None:
        """If a line-up is on, put on what it has due `ahead` seconds from now."""
        self._changed_to(await follow(db, await self.office_time(db, ahead)))

    def _changed_to(self, change: Change | None) -> None:
        """Note what a line-up put on, and hold on to the show it opens, for its first song."""
        if change is None:
            return
        self._opening = change.opening
        self.note(f"{change.name} is on, from the {change.lineup} line-up")

    async def keep_lineup_on(self, lineup_id: int) -> None:
        """Put a line-up back on after the station or playlist it was playing was deleted,
        which took the source with it. That slot is a gap now."""
        async with self.lock, self._sessions() as db:
            lineup = await db.get(Lineup, lineup_id)
            if lineup is None or await db.get(SourceState, 1):
                return
            self._changed_to(await put_on(db, lineup, await self.office_time(db)))
        if self._radio:
            await self._radio.top_up()
        await self.changed()

    async def recover(self) -> None:
        """After a restart. Songs still on the speakers GuildFM picked back up stay as they were.
        Anything else is no longer playing or locked in: a locked request goes back to the top of
        the vote, and a locked playlist song is let go."""
        playing, lined_up = self._controller.current_key, self._controller.upcoming_keys
        async with self._sessions() as db:
            await best_voted(db)
            await ai_picks(db)
            entries = await db.scalars(
                select(QueueEntry).where(QueueEntry.state != EntryState.WAITING)
            )
            for entry in entries.unique().all():
                key = self.item(entry).key
                if entry.state == EntryState.PLAYING:
                    if key != playing:
                        await db.delete(entry)
                elif key in lined_up:
                    continue
                elif entry.requested_by is None:
                    await give_back(db, entry.track_id)
                    await db.delete(entry)
                else:
                    entry.state, entry.pinned_position = EntryState.WAITING, 1
            await db.commit()

    async def _lock_head(self, db: AsyncSession) -> QueueEntry | None:
        """Take the top request out of the vote and mark it as next, or, with no requests
        waiting, the playing playlist's next song. Placed requests move up a place."""
        entries, _ = await waiting(db)
        if not entries:
            return await self._from_source(db)
        head = entries[0]
        head.state = EntryState.NEXT
        head.pinned_position = None
        for entry in entries[1:]:
            if entry.pinned_position is not None:
                entry.pinned_position = max(1, entry.pinned_position - 1)
        await db.commit()
        return head

    async def _from_source(self, db: AsyncSession) -> QueueEntry | None:
        """The next song from the playlist or station filling the gaps, as a locked-in queue
        entry with no requester. With nothing filling them, and "requests only" not chosen, the
        queue has run out, and the settings say which station takes over."""
        source = await current_source(db)
        if source is None:
            if await requests_only(db):
                return None
            source = await self._run_out(db)
        playlist_id, station_id = source.playlist_id, source.station_id
        queued = set(await db.scalars(select(QueueEntry.track_id)))
        restart = await get_pref(db, "queue_runs_out") == "restart_playlist"
        track_id = await take_next(db, queued, restart=restart)
        if station_id and self._radio:
            await self._radio.top_up()
        if track_id is None:
            if playlist_id and await current_source(db) is None:
                await self._run_out(db)  # the playlist played to the end
            return None
        entry = QueueEntry(
            track_id=track_id,
            playlist_id=playlist_id,
            station_id=station_id,
            added_at=self._clock(),
            state=EntryState.NEXT,
        )
        db.add(entry)
        await db.commit()
        if self._opening and self._opening.station_id == station_id:
            # The first song of a line-up's show: the show opens with it.
            self._opener, self._opening = (entry.id, self._opening.until), None
        # Read back with its track, which a new entry doesn't have loaded.
        return await db.get(QueueEntry, entry.id, populate_existing=True)

    async def _run_out(self, db: AsyncSession) -> SourceState:
        """Nothing is left to fill the gaps: put the default station on, if that's the setting
        and there is one, otherwise AI picks. It needs a moment to pick its first songs."""
        station = await gap_station(db)
        source = await play_station(db, station)
        self.note(f"The queue ran out, so {station.name} is on")
        if self._radio:
            await self._radio.top_up()
        return source

    async def _unlock(self, entry_id: int) -> None:
        async with self._sessions() as db:
            entry = await db.get(QueueEntry, entry_id)
            if entry and entry.state == EntryState.NEXT:
                if entry.requested_by is None:
                    # A playlist song: let it go, and the playlist can offer it again.
                    await give_back(db, entry.track_id)
                    await db.delete(entry)
                else:
                    entry.state, entry.pinned_position = EntryState.WAITING, 1
                await db.commit()

    async def keep_fed(self) -> None:
        """After each reading of the speakers: line up the next request when the current song
        is nearly over, or start one if the queue had run dry."""
        controller = self._controller
        if not controller.in_control:
            return
        status, left = controller.status, controller.time_left
        if status != Status.IDLE:
            self._stalls = 0
        if status == Status.PLAYING and left is not None and left > LEAD_SECONDS:
            return
        if status not in (Status.PLAYING, Status.IDLE):
            return
        # When the next song will start, which is what a line-up goes by.
        ahead = (controller.seconds_left() or 0) if status == Status.PLAYING else 0
        async with self.lock, self._sessions() as db:
            lined_up = await in_state(db, EntryState.NEXT)
            if lined_up and status == Status.IDLE:
                # The speakers stopped with a song lined up, so it couldn't play, often just a
                # hiccup. After a few readings GuildFM has them try it again, and if they stop
                # again, it lets the song go and carries on. The first try is straight away when
                # they stopped at the end of a clip, as they often do after the DJ.
                self._stalls += 1
                first_try = self._retried != lined_up.id
                at_once = first_try and controller.stopped_after_clip
                if self._stalls < STALLED_READINGS and not at_once:
                    return
                self._stalls = 0
                if first_try:
                    self._retried = lined_up.id
                    log.info(
                        "%s didn't start on the speakers; trying it again", lined_up.track.title
                    )
                    if await controller.play_again(self.item(lined_up)):
                        return
                await self._let_go(db, lined_up)
                lined_up = None
            # Anything else after the current song had played, and the speakers went back to it.
            await controller.clear_ahead({self.item(lined_up).key} if lined_up else set())
            if lined_up:
                return
            await self._follow(db, ahead)
            await self._crossfade(db)
            await self._prepare_shows(db, ahead)
            head = await self._lock_head(db)
            if head is None:
                return
            entry_id, item = head.id, self.item(head)
        opens = self._opener[1] if self._opener and self._opener[0] == entry_id else None
        try:
            if status == Status.IDLE:
                await controller.play_now(item)
            else:
                await controller.queue_next(item)
                for callback in self.on_lined_up:
                    await callback(entry_id, item.key, opens)
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

    async def previous(self) -> None:
        """Go back a song, or start this one again if it's well under way. Going back leaves the
        song that was playing next in line on the speakers, so it's next here again too."""
        controller = self._controller
        action = controller.previous_action
        requeued = None
        if action == "back":
            async with self.lock, self._sessions() as db:
                playing = await in_state(db, EntryState.PLAYING)
                if playing and not await in_state(db, EntryState.NEXT):
                    playing.state, requeued = EntryState.NEXT, playing.id
                    await db.commit()
        try:
            await controller.previous(action)
        except Exception:
            if requeued:
                await self._set_state(requeued, EntryState.PLAYING)
            raise
        await self.changed()

    async def _set_state(self, entry_id: int, state: EntryState) -> None:
        async with self._sessions() as db:
            entry = await db.get(QueueEntry, entry_id)
            if entry:
                entry.state = state
                await db.commit()

    async def switch(self, choice: Choice) -> bool:
        """Make a playlist or station fill the gaps between requests from the next song on, or
        nothing ("requests only") for None. A song from the old source already lined up on the
        speakers comes back off them, so the switch still comes straight after the current
        song. False when that was the source already."""
        async with self._sessions() as db:
            source = await current_source(db)
            # Picking a line-up's playlist or station by hand ends the line-up.
            alone = bool(source and source.lineup_id is None)
            if choice is None:
                same = await requests_only(db)
            elif isinstance(choice, Lineup):
                same = bool(source and source.lineup_id == choice.id)
            elif isinstance(choice, Playlist):
                same = alone and source.playlist_id == choice.id
            else:
                same = alone and source.station_id == choice.id
            if same:
                return False
            lined_up = await in_state(db, EntryState.NEXT)
        stale = lined_up if lined_up and lined_up.requested_by is None else None
        if stale and self._controller.in_control:
            try:
                await self._controller.unqueue(self.item(stale))
            except SpeakersUnavailable, SpeakersRefused:
                log.warning("Couldn't take the old playlist's song off the speakers", exc_info=True)
                stale = None  # it plays, and the switch comes a song later
        elif stale:
            stale = None  # not driving the speakers, so it stays where it is

        async with self.lock, self._sessions() as db:
            if stale:
                entry = await db.get(QueueEntry, stale.id)
                if entry and entry.state == EntryState.NEXT:
                    await give_back(db, entry.track_id)
                    await db.delete(entry)
            if choice is None:
                await choose_requests_only(db)
            elif isinstance(choice, Lineup):
                lineup = await db.get(Lineup, choice.id)
                self._changed_to(await put_on(db, lineup, await self.office_time(db)))
            elif isinstance(choice, Playlist):
                await play_playlist(db, await db.get(Playlist, choice.id))
            else:
                await play_station(db, await db.get(Station, choice.id))
        await self.changed()
        if self._radio:
            await self._radio.top_up()
        # Lines up the new source's song in place of the one taken off, or starts it if the
        # music had run out.
        await self.keep_fed()
        return True

    async def _crossfade(self, db: AsyncSession) -> None:
        """The speakers crossfade between songs while a station that asks for it fills the
        gaps, on its own or as a line-up's show, and not otherwise. Set as each song is lined
        up, so it holds for the change of song coming."""
        source = await current_source(db)
        station = source.station if source and source.station_id else None
        await self._controller.set_crossfade(bool(station and station.crossfade))

    async def apply_crossfade(self) -> None:
        """A station's crossfade switch changed: set the speakers to match now."""
        async with self._sessions() as db:
            await self._crossfade(db)

    async def _let_go(self, db: AsyncSession, entry: QueueEntry) -> None:
        """Give up on a lined-up song that couldn't play: off the speakers and out of the queue."""
        title = entry.track.title
        try:
            await self._controller.unqueue(self.item(entry))
        except SpeakersUnavailable, SpeakersRefused:
            log.warning("Couldn't take a song that wouldn't play off the speakers", exc_info=True)
        await db.delete(entry)
        await db.commit()
        log.warning("%s wouldn't play on the speakers, so GuildFM skipped it", title)
        self.note(f"{title} wouldn't play, so it was skipped")

    async def _prepare_shows(self, db: AsyncSession, ahead: float) -> None:
        """A line-up's show starting soon has its station pick its first songs now, so it starts
        without waiting for the AI."""
        source = await db.get(SourceState, 1)
        if self._radio is None or source is None or source.lineup_id is None:
            return
        lineup = await db.get(Lineup, source.lineup_id)
        minute = minute_of(await self.office_time(db, ahead))
        for slot in lineup.slots:
            soon = 0 < slot.start - minute <= PREPARE_MINUTES
            if soon and slot.station_id and slot.station_id != source.station_id:
                self._radio.prepare(slot.station_id)

    async def _first_up(self) -> list[QueueItem]:
        """What to play when GuildFM takes the speakers over and has nothing lined up."""
        async with self.lock, self._sessions() as db:
            await self._follow(db)
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
                        playlist_id=entry.playlist_id,
                        station_id=entry.station_id,
                        played_at=self._clock(),
                        upvotes=tally.up,
                        downvotes=tally.down,
                    )
                )
                if entry.requester:
                    self.note(
                        f"Now playing {entry.track.title}, "
                        f"requested by {entry.requester.display_name}"
                    )
                    joined = await consider_for_best_voted(
                        db,
                        entry.track_id,
                        tally.up,
                        more_than=await get_pref(db, "best_voted_min_upvotes"),
                        size=await get_pref(db, "best_voted_size"),
                    )
                    if joined:
                        self.note(f"{entry.track.title} made it into Best Voted")
                elif entry.playlist:
                    self.note(f"Now playing {entry.track.title} from {entry.playlist.name}")
                elif entry.station:
                    self.note(f"Now playing {entry.track.title} on {entry.station.name}")
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
