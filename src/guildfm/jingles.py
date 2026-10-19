"""Jingles: short idents that AI stations play between songs, as a real station would.

System idents are GuildFM's own and can play on any AI station; station idents belong to one
station. They're MP3s in the media folder, where the speakers fetch them, like announcements.

The AI that picks a station's songs also marks the ones to play an ident before, and which kind
(see radio.py). When one of those is lined up on the speakers, a jingle of that kind goes to the
announcer, to play in the pause before the song, ahead of anything the DJ says there. Never at
two song changes in a row, and never the same jingle twice running when there's another.
"""

import logging
import random
import secrets
import time
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.announcements import Announcer, Spoken
from guildfm.models import JINGLES, AnnounceMode, Jingle, JingleKind, PickNote, QueueEntry
from guildfm.playlists import current_source
from guildfm.speech import Clip, mp3_seconds

log = logging.getLogger(__name__)

MAX_BYTES = 5 * 1024 * 1024
MAX_SECONDS = 60
GAP = 2  # song changes from one jingle to the next, at least


class JingleError(Exception):
    """A file that can't be a jingle. The message is fit to show people."""


def folder(media_dir: Path) -> Path:
    return media_dir / JINGLES


def _looks_like_mp3(data: bytes) -> bool:
    """An ID3 tag or an MPEG frame header first, as MP3s start."""
    return data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)


def add_jingle(
    db: AsyncSession, media_dir: Path, data: bytes, name: str, station_id: int | None = None
) -> Jingle:
    """Save an MP3 as a jingle: a station ident for `station_id`, or a system ident. The caller
    commits."""
    if len(data) > MAX_BYTES:
        raise JingleError("That file is too big for a jingle.")
    seconds = mp3_seconds(data) if _looks_like_mp3(data) else 0
    if not seconds:
        raise JingleError("That isn't an MP3. Jingles need to be MP3 files.")
    if seconds > MAX_SECONDS:
        raise JingleError(f"That's {round(seconds)} seconds long. Jingles can be up to a minute.")
    place = folder(media_dir)
    place.mkdir(parents=True, exist_ok=True)
    file = f"{secrets.token_urlsafe(12)}.mp3"
    (place / file).write_bytes(data)
    jingle = Jingle(
        kind=JingleKind.STATION if station_id else JingleKind.SYSTEM,
        station_id=station_id,
        name=name,
        file=file,
        seconds=seconds,
        created_at=time.time(),
    )
    db.add(jingle)
    return jingle


def forget(media_dir: Path, jingle: Jingle) -> None:
    """Delete the jingle's file. Its row goes separately."""
    (folder(media_dir) / jingle.file).unlink(missing_ok=True)


async def playable(db: AsyncSession, station_id: int | None) -> list[Jingle]:
    """The jingles a station can play: the system idents and its own station idents."""
    theirs = Jingle.station_id.is_(None)
    if station_id is not None:
        theirs = or_(theirs, Jingle.station_id == station_id)
    return list(await db.scalars(select(Jingle).where(theirs).order_by(Jingle.id)))


def kinds(jingles: list[Jingle]) -> tuple[str, ...]:
    """The kinds of ident there are to play, system idents first."""
    return tuple(kind.value for kind in JingleKind if any(j.kind == kind for j in jingles))


class Rotation:
    """Which jingle plays at each song change, from the AI's marks: never at two song changes
    in a row, and never the same one twice running when there's another of its kind."""

    def __init__(self) -> None:
        self._changes = GAP  # song changes since the last jingle
        self._last: dict[str, int] = {}  # kind: the jingle of that kind that played last

    def opening(self, jingles: list[Jingle]) -> Jingle | None:
        """A line-up's show starting: one of its station idents, however lately the last
        jingle played."""
        options = [jingle for jingle in jingles if jingle.kind == JingleKind.STATION]
        if not options:
            self._changes += 1
            return None
        last = self._last.get(JingleKind.STATION.value)
        chosen = random.choice([jingle for jingle in options if jingle.id != last] or options)
        self._last[JingleKind.STATION.value] = chosen.id
        self._changes = 0
        return chosen

    def next(self, kind: str | None, jingles: list[Jingle]) -> Jingle | None:
        """The next song change, marked for an ident of `kind` or not: the jingle to play."""
        self._changes += 1
        options = [jingle for jingle in jingles if jingle.kind == kind]
        if not options or self._changes < GAP:
            return None
        fresh = [jingle for jingle in options if jingle.id != self._last.get(kind)] or options
        chosen = random.choice(fresh)
        self._last[kind] = chosen.id
        self._changes = 0
        return chosen


class JinglePlayer:
    def __init__(self, sessionmaker, announcer: Announcer, media_dir: Path) -> None:
        self._sessions = sessionmaker
        self._announcer = announcer
        self._media = media_dir
        self._rotation = Rotation()

    async def lined_up(self, entry_id: int, key: str, opens: int | None = None) -> None:
        try:
            await self.play(entry_id, key, opens)
        except Exception:
            log.exception("Couldn't line up a jingle")

    async def play(self, entry_id: int, key: str, opens: int | None = None) -> Spoken | None:
        """The song lined up as `entry_id` is coming next: if the AI marked it for an ident,
        queue one for the pause before it. A song that `opens` a line-up's show gets one of the
        station's own idents. Returns the jingle queued, if any."""
        async with self._sessions() as db:
            source = await current_source(db)
            station = source.station if source and source.station_id else None
            entry = await db.get(QueueEntry, entry_id)
            if station is None or entry is None:
                return None
            marked = None
            if station.jingles and entry.requested_by is None:
                picked = await db.get(PickNote, entry.track_id)
                marked = picked.ident if picked else None
                if opens is not None:
                    marked = JingleKind.STATION.value
            jingles = await playable(db, station.id) if marked else []
        if opens is not None:
            jingle = self._rotation.opening(jingles)
        else:
            jingle = self._rotation.next(marked, jingles)
        if jingle is None:
            return None
        clip = Clip(folder(self._media) / jingle.file, jingle.seconds, JINGLES)
        spoken = Spoken(
            f"{jingle.kind.value.capitalize()} ident: {jingle.name}",
            clip,
            None,
            AnnounceMode.AFTER,
            dj=True,
            for_key=key,
            jingle=True,
            title=jingle.name,
        )
        self._announcer.say(spoken)
        return spoken
