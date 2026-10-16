"""Playlists, the Best Voted playlist GuildFM keeps itself, and the playlist playing as the source.

The source fills the gaps between requests. Each time round it has its own order (shuffled, or
as listed); songs thumbed down enough are skipped for that time round only. A playlist that's
switched away from keeps its place, and carries on from there when it's put back on.
"""

import random
import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.models import Playlist, PlaylistKind, PlaylistTrack, SourceState

BEST_VOTED = "Best Voted"
UPCOMING = 3  # how many of the source's next songs the Queue screen shows


async def best_voted(db: AsyncSession) -> Playlist:
    """The Best Voted playlist, made on first use. It shuffles unless someone turns that off."""
    playlist = await db.scalar(select(Playlist).where(Playlist.kind == PlaylistKind.BEST_VOTED))
    if playlist is None:
        playlist = Playlist(
            name=BEST_VOTED, kind=PlaylistKind.BEST_VOTED, created_at=time.time(), shuffle=True
        )
        db.add(playlist)
        await db.commit()
    return playlist


async def tracks_of(db: AsyncSession, playlist_id: int) -> list[PlaylistTrack]:
    rows = await db.scalars(
        select(PlaylistTrack)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .order_by(PlaylistTrack.position)
    )
    return list(rows.unique().all())


async def add_track(db: AsyncSession, playlist: Playlist, track_id: str, upvotes: int = 0) -> bool:
    """Add a track at the end. False if it was already there."""
    if await db.get(PlaylistTrack, (playlist.id, track_id)):
        return False
    last = await db.scalar(
        select(func.max(PlaylistTrack.position)).where(PlaylistTrack.playlist_id == playlist.id)
    )
    db.add(
        PlaylistTrack(
            playlist_id=playlist.id,
            track_id=track_id,
            position=(last or 0) + 1,
            added_at=time.time(),
            upvotes=upvotes,
        )
    )
    source = await db.get(SourceState, 1)
    if source and source.playlist_id == playlist.id:
        # The playlist is playing: the new song joins this time round too, somewhere later.
        order = list(source.order)
        later = random.randint(source.cursor, len(order)) if playlist.shuffle else len(order)
        order.insert(later, track_id)
        source.order = order
    return True


async def consider_for_best_voted(
    db: AsyncSession, track_id: str, upvotes: int, *, more_than: int, size: int
) -> bool:
    """A request has just started playing with `upvotes`. If that's more than `more_than`, it
    joins Best Voted, pushing out the track with the fewest upvotes (the oldest on a tie) when
    the playlist is full. A newcomer needs at least as many upvotes as the track it replaces."""
    if upvotes <= more_than:
        return False
    playlist = await best_voted(db)
    existing = await db.get(PlaylistTrack, (playlist.id, track_id))
    if existing:
        existing.upvotes = max(existing.upvotes, upvotes)
        await db.commit()
        return True

    entries = await tracks_of(db, playlist.id)
    if len(entries) >= size:
        weakest = min(entries, key=lambda entry: (entry.upvotes, entry.added_at))
        if upvotes < weakest.upvotes:
            return False
        await db.delete(weakest)
    await add_track(db, playlist, track_id, upvotes=upvotes)
    await db.commit()
    return True


# The source


def _order(track_ids: list[str], shuffle: bool) -> list[str]:
    order = list(track_ids)
    if shuffle:
        random.shuffle(order)
    return order


async def _set_aside(db: AsyncSession) -> None:
    """Keep the playing playlist's place, so putting it back on carries on from there."""
    source = await current_source(db)
    if source:
        source.playlist.resume = {
            "order": source.order,
            "cursor": source.cursor,
            "skipped": source.skipped,
            "downvotes": source.downvotes,
        }


async def play_playlist(db: AsyncSession, playlist: Playlist) -> SourceState:
    """Make `playlist` the source. It carries on where it left off if it was switched away
    from part way through, otherwise it starts from the top (or a fresh shuffle)."""
    await _set_aside(db)
    ids = [entry.track_id for entry in await tracks_of(db, playlist.id)]
    saved = playlist.resume
    if saved:
        present = set(ids) - set(saved["skipped"])
        if not any(track_id in present for track_id in saved["order"][saved["cursor"] :]):
            saved = None  # it was on its last song, so start afresh
    if saved:
        order, cursor = list(saved["order"]), saved["cursor"]
        known = set(order)
        # Songs added since it was set aside join the rest of this time round.
        for track_id in ids:
            if track_id not in known:
                later = random.randint(cursor, len(order)) if playlist.shuffle else len(order)
                order.insert(later, track_id)
        skipped, downvotes = saved["skipped"], saved["downvotes"]
    else:
        order, cursor, skipped, downvotes = _order(ids, playlist.shuffle), 0, [], {}
    playlist.resume = None
    source = await db.merge(
        SourceState(
            id=1,
            playlist_id=playlist.id,
            order=order,
            cursor=cursor,
            skipped=skipped,
            downvotes=downvotes,
        )
    )
    await db.commit()
    return source


async def stop_playlist(db: AsyncSession) -> None:
    source = await current_source(db)
    if source:
        await _set_aside(db)
        await db.delete(source)
        await db.commit()


async def give_back(db: AsyncSession, track_id: str) -> None:
    """A song taken from the source that won't play after all is next again."""
    source = await current_source(db)
    if source and source.cursor > 0 and source.order[source.cursor - 1] == track_id:
        source.cursor -= 1


async def current_source(db: AsyncSession) -> SourceState | None:
    return await db.get(SourceState, 1)


async def upcoming(db: AsyncSession, queued: set[str], count: int = UPCOMING) -> list[str]:
    """The source's next `count` songs, leaving out skipped ones and any already queued."""
    source = await current_source(db)
    if source is None:
        return []
    still_in = {entry.track_id for entry in await tracks_of(db, source.playlist_id)}
    found = []
    for track_id in source.order[source.cursor :]:
        if track_id in still_in and track_id not in source.skipped and track_id not in queued:
            found.append(track_id)
            if len(found) == count:
                break
    return found


async def take_next(db: AsyncSession, queued: set[str], *, restart: bool) -> str | None:
    """The source's next song, moving past it. At the end, start the playlist over if
    `restart`, otherwise stop playing it. None when there's nothing to take."""
    source = await current_source(db)
    if source is None:
        return None
    for attempt in range(2):
        still_in = {entry.track_id for entry in await tracks_of(db, source.playlist_id)}
        while source.cursor < len(source.order):
            track_id = source.order[source.cursor]
            source.cursor += 1
            if track_id in still_in and track_id not in source.skipped and track_id not in queued:
                await db.commit()
                return track_id
        if attempt == 0 and restart and still_in:
            source.order = _order(
                [entry.track_id for entry in await tracks_of(db, source.playlist_id)],
                source.playlist.shuffle,
            )
            source.cursor, source.skipped, source.downvotes = 0, [], {}
            continue
        break
    await db.delete(source)
    await db.commit()
    return None


async def thumb_down(
    db: AsyncSession, track_id: str, user_id: int, down: bool, threshold: int
) -> bool:
    """Record (or take back) a thumbs down on one of the source's upcoming songs. True when
    that's enough to skip it this time round."""
    source = await current_source(db)
    if source is None or track_id not in source.order[source.cursor :]:
        return False
    voters = set(source.downvotes.get(track_id, []))
    if down:
        voters.add(user_id)
    else:
        voters.discard(user_id)
    source.downvotes = {**source.downvotes, track_id: sorted(voters)}
    skipped = len(voters) >= -threshold
    if skipped and track_id not in source.skipped:
        source.skipped = [*source.skipped, track_id]
    await db.commit()
    return skipped
