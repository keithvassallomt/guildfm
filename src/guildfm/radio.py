"""AI radio: stations whose songs the AI picks, found on Spotify by name.

A station on as the source keeps a few songs picked ahead. When it runs low, GuildFM asks the AI
for another batch, from the station's description and what has played lately (and the time,
weather and music news, with global awareness on), then finds each on Spotify. Anything played
recently, picked by the station lately, already queued, or explicit while that's turned off is
left out. Votes never reach the AI, so a station's taste stays its own. With jingles to play, the
AI also marks the odd song to have an ident before it (see jingles.py).

When the AI can't pick (OpenAI or Spotify is down, or out of credit), the station carries on with
songs heard before, so the music doesn't stop, and the AI is asked again when those run low.

The AI picks station, which GuildFM keeps itself, follows whatever has been playing. It takes
over when the queue runs out, unless the settings say otherwise.
"""

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.ai import AIClient, AIError, object_schema
from guildfm.awareness import Awareness
from guildfm.jingles import kinds, playable
from guildfm.models import PickNote, Play, QueueEntry, Station, StationKind, Track
from guildfm.playlists import best_voted, current_source, tracks_of
from guildfm.prefs import get_pref
from guildfm.spotify import SpotifyClient, SpotifyError, SpotifyTrack, remember

log = logging.getLogger(__name__)

LOW = 3  # songs left in a station's order before another batch is picked
BATCH = 8  # songs added at a time
SPARE = 4  # songs asked for on top, since the odd one isn't on Spotify
REMEMBERED = 150  # picks a station remembers, so it doesn't repeat itself
KEPT_TAKEN = 5  # songs already taken that stay in the order, for give_back
RECENT_PLAYS = 30  # recent plays shown to the AI
SHOWN_PICKS = 40  # of the station's own picks, shown to the AI
RETRY_SECONDS = 60  # after a batch that found nothing, the wait before asking again
SEARCHES = 4  # Spotify searches at once
NOTES_KEPT = 500  # why each song was picked, for the DJ, and the idents to play

AI_PICKS = "AI picks"
AI_PICKS_BRIEF = (
    "Songs that follow on from what has been playing today. With nothing played yet, music "
    "most people in an office would enjoy."
)

INSTRUCTIONS = (
    "You are the music director of {name}, a radio station playing over the speakers in an "
    "office in the UK. Pick real, released recordings that are on Spotify, using each song's "
    "best-known title and main artist. Vary the artists, and don't pick a song more than once."
)
IDENTS = {
    "system": "system, an ident for GuildFM, the network the station is part of",
    "station": "station, this station's own ident",
}


def picks_schema(idents: Sequence[str]) -> dict[str, Any]:
    """The AI's answer: songs in order, each with why it fits and, with jingles to play,
    whether an ident goes before it."""
    song = {
        "title": {"type": "string"},
        "artist": {"type": "string"},
        "note": {"type": "string", "description": "Why it fits, in a few words, for the DJ."},
    }
    if idents:
        song["ident"] = {
            "type": "string",
            "enum": ["none", *idents],
            "description": "A jingle to play just before this song, or none.",
        }
    return object_schema(songs={"type": "array", "items": object_schema(**song)})


async def ai_picks(db: AsyncSession) -> Station:
    """The AI picks station, made on first use."""
    station = await db.scalar(select(Station).where(Station.kind == StationKind.AI_PICKS))
    if station is None:
        station = Station(
            name=AI_PICKS,
            kind=StationKind.AI_PICKS,
            description=AI_PICKS_BRIEF,
            created_at=time.time(),
        )
        db.add(station)
        await db.commit()
    return station


def _plain(text: str) -> str:
    """Lower case, without "the", punctuation or brackets, for comparing artist names."""
    words = re.sub(r"[^\w\s]", " ", re.sub(r"\(.*?\)|\[.*?\]", " ", text.lower())).split()
    return " ".join(word for word in words if word != "the")


def same_artist(wanted: str, found: str) -> bool:
    wanted, found = _plain(wanted), _plain(found)
    return bool(wanted) and (wanted in found or found in wanted)


def _song(track: Track) -> str:
    return f"{track.artists} – {track.title}"


@dataclass(frozen=True)
class Taste:
    """What picking songs needs to know about a station, saved or not."""

    name: str
    brief: str
    aware: bool  # global awareness
    picked: list[str]  # its recent picks, oldest first
    idents: tuple[str, ...] = ()  # the kinds of jingle it can play: "system", "station"

    @classmethod
    def of(cls, station: Station, idents: tuple[str, ...] = ()) -> Taste:
        return cls(
            station.name, station.description, station.global_awareness, station.picked, idents
        )


@dataclass(frozen=True)
class Pick:
    track: SpotifyTrack
    note: str  # why it fits, for the DJ
    ident: str | None  # the kind of jingle to play before it, if any


class Radio:
    def __init__(
        self,
        sessionmaker,
        ai: AIClient,
        spotify: SpotifyClient,
        awareness: Awareness,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sessions = sessionmaker
        self._ai = ai
        self._spotify = spotify
        self._awareness = awareness
        self._clock = clock
        self._monotonic = monotonic
        self._task: asyncio.Task | None = None
        self._failed_at: dict[int, float] = {}  # station id: when a batch last found nothing
        # Run after a batch is added, so the queue can line the first one up.
        self.on_picked: list[Callable[[], Awaitable[None]]] = []

    def now(self) -> datetime:
        return self._clock()

    async def close(self) -> None:
        """Stop picking, before the database closes."""
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def settle(self) -> None:
        """Wait for a batch that's being picked. For tests."""
        if self._task:
            await self._task

    async def top_up(self) -> None:
        """If a station is the source and running low, pick more in the background."""
        if self._task and not self._task.done():
            return
        async with self._sessions() as db:
            source = await current_source(db)
            if source is None or source.station_id is None:
                return
            station_id, left = source.station_id, len(source.order) - source.cursor
        if left >= LOW:
            return
        if self._monotonic() - self._failed_at.get(station_id, float("-inf")) < RETRY_SECONDS:
            return
        self._task = asyncio.create_task(self._top_up(station_id))

    async def _top_up(self, station_id: int) -> None:
        try:
            added = await self.pick(station_id)
        except AIError as error:
            log.warning("The AI couldn't pick songs for a station: %s", error)
            added = 0
        except Exception:
            log.exception("Picking songs for a station failed")
            added = 0
        if not added:
            self._failed_at[station_id] = self._monotonic()
            try:
                added = await self.replay(station_id)
            except Exception:
                log.exception("Lining up a station's songs from before failed")
        if not added:
            return
        for callback in self.on_picked:
            await callback()

    async def pick(self, station_id: int) -> int:
        """Pick a batch of songs for the station, and add them to the source's order if it's
        still on. Returns how many were added."""
        async with self._sessions() as db:
            station = await db.get(Station, station_id)
            if station is None:
                return 0
            idents = kinds(await playable(db, station_id)) if station.jingles else ()
            taste = Taste.of(station, idents)
            source = await current_source(db)
            lined_up = set()
            if source and source.station_id == station_id:
                lined_up = set(source.order[source.cursor :])
        chosen = await self.candidates(taste, BATCH, lined_up)
        if not chosen:
            log.warning("None of the AI's picks for %s could be played", taste.name)
            return 0

        async with self._sessions() as db:
            await remember(db, [pick.track for pick in chosen])
            station = await db.get(Station, station_id)
            source = await current_source(db)
            if station is None or source is None or source.station_id != station_id:
                return 0  # switched away meanwhile
            keep = max(0, source.cursor - KEPT_TAKEN)
            ids = [pick.track.id for pick in chosen]
            source.order = source.order[keep:] + ids
            source.cursor -= keep
            station.picked = (station.picked + ids)[-REMEMBERED:]
            # Why each was picked and any ident before it, kept so they survive a restart.
            now = self._clock().timestamp()
            for pick in chosen:
                await db.merge(
                    PickNote(
                        track_id=pick.track.id, note=pick.note, ident=pick.ident, picked_at=now
                    )
                )
            newest = select(PickNote.track_id).order_by(PickNote.picked_at.desc()).limit(NOTES_KEPT)
            await db.execute(delete(PickNote).where(PickNote.track_id.not_in(newest)))
            await db.commit()
        return len(chosen)

    async def replay(self, station_id: int) -> int:
        """For when the AI can't pick: songs heard before, so the music carries on. The
        station's own earlier picks first, then songs it played longer ago, then Best Voted,
        each the longest since played first. Anything played lately, queued, or explicit while
        that's turned off is left out, as ever. Returns how many were added."""
        async with self._sessions() as db:
            station = await db.get(Station, station_id)
            source = await current_source(db)
            if station is None or source is None or source.station_id != station_id:
                return 0
            since = time.time() - await get_pref(db, "recently_played_hours") * 3600
            avoid = set(await db.scalars(select(Play.track_id).where(Play.played_at >= since)))
            avoid |= set(await db.scalars(select(QueueEntry.track_id)))
            avoid |= set(source.order[source.cursor :])
            if not await get_pref(db, "allow_explicit"):
                avoid |= set(await db.scalars(select(Track.id).where(Track.explicit)))
            played_here = await db.scalars(
                select(Play.track_id).where(Play.station_id == station_id).order_by(Play.id)
            )
            favourites = await tracks_of(db, (await best_voted(db)).id)
            last_played = dict(
                (
                    await db.execute(
                        select(Play.track_id, func.max(Play.played_at)).group_by(Play.track_id)
                    )
                ).all()
            )
            chosen: list[str] = []
            pools = (station.picked, played_here.all(), [entry.track_id for entry in favourites])
            for pool in pools:
                fresh = [track_id for track_id in dict.fromkeys(pool) if track_id not in avoid]
                fresh.sort(key=lambda track_id: last_played.get(track_id, 0.0))
                chosen += fresh[: BATCH - len(chosen)]
                avoid |= set(fresh)
            if not chosen:
                return 0
            keep = max(0, source.cursor - KEPT_TAKEN)
            source.order = source.order[keep:] + chosen
            source.cursor -= keep
            await db.commit()
        log.warning("%s is playing songs from before until the AI can pick again", station.name)
        return len(chosen)

    async def candidates(
        self, taste: Taste, count: int, avoid: set[str] | None = None
    ) -> list[Pick]:
        """Up to `count` songs for a station like `taste`, found on Spotify, in the order the
        AI wants them played, each with why it fits and any ident to play before it. Anything
        played recently, queued, picked by the station lately or in `avoid` is left out.
        Nothing is saved."""
        avoid = set(avoid or ())
        async with self._sessions() as db:
            explicit = await get_pref(db, "allow_explicit")
            zone = ZoneInfo(await get_pref(db, "timezone"))
            location = await get_pref(db, "weather_location")
            recently = await get_pref(db, "recently_played_hours")
            recent = (
                await db.scalars(select(Play).order_by(Play.id.desc()).limit(RECENT_PLAYS))
            ).unique()
            plays = [_song(play.track) for play in recent]
            since = time.time() - recently * 3600
            avoid |= set(await db.scalars(select(Play.track_id).where(Play.played_at >= since)))
            avoid |= set(await db.scalars(select(QueueEntry.track_id)))
            avoid |= set(taste.picked)
            shown = taste.picked[-SHOWN_PICKS:]
            found = {t.id: t for t in await db.scalars(select(Track).where(Track.id.in_(shown)))}
            picked = [_song(found[track_id]) for track_id in reversed(shown) if track_id in found]

        context = None
        if taste.aware:
            context = await self._awareness.context(location, self._clock().astimezone(zone))
        asked = count + SPARE
        prompt = self._prompt(taste.brief, context, plays, picked, explicit, asked, taste.idents)
        instructions = INSTRUCTIONS.format(name=taste.name)
        answer = await self._ai.json(instructions, prompt, "picks", picks_schema(taste.idents))
        songs = answer.get("songs", [])[:asked]

        chosen: list[Pick] = []
        for song, track in zip(songs, await self._find_all(songs, explicit), strict=True):
            if track and track.id not in avoid and len(chosen) < count:
                avoid.add(track.id)
                ident = song.get("ident")
                ident = ident if ident in taste.idents else None
                chosen.append(Pick(track, song.get("note", ""), ident))
        return chosen

    @staticmethod
    def _prompt(
        brief: str,
        context: str | None,
        plays: list[str],
        picked: list[str],
        explicit: bool,
        asked: int,
        idents: Sequence[str] = (),
    ) -> str:
        parts = [f"Station brief: {brief}"]
        if context:
            parts.append(
                f"Let this steer the picks where it fits, without overdoing it:\n{context}"
            )
        if plays:
            parts.append("Played lately, newest first. Don't pick these:\n" + "\n".join(plays))
        if picked:
            parts.append(
                "This station's own recent picks. Don't pick these again:\n" + "\n".join(picked)
            )
        if not explicit:
            parts.append("Don't pick explicit songs.")
        if idents:
            parts.append(
                "Idents are short jingles played in the pause before a song. Mark the odd song to "
                "have one, about one in four, where it helps the flow: at a change of mood or "
                "pace, or to start a new run of songs. Never two songs in a row. The kinds: "
                + "; ".join(IDENTS[kind] for kind in idents)
                + "."
            )
        parts.append(f"Pick {asked} songs, in the order they should play.")
        return "\n\n".join(parts)

    async def _find_all(
        self, songs: list[dict[str, Any]], explicit: bool
    ) -> list[SpotifyTrack | None]:
        searches = asyncio.Semaphore(SEARCHES)

        async def find(song: dict[str, Any]) -> SpotifyTrack | None:
            async with searches:
                return await self._find(song.get("title", ""), song.get("artist", ""), explicit)

        return list(await asyncio.gather(*(find(song) for song in songs)))

    async def _find(self, title: str, artist: str, explicit: bool) -> SpotifyTrack | None:
        """The song on Spotify: by title and artist, then more loosely. The artist has to match
        either way, so a cover or a karaoke version doesn't slip in."""
        for query in (f'track:"{title}" artist:"{artist}"', f"{title} {artist}"):
            try:
                found = await self._spotify.search(query, pages=1)
            except SpotifyError as error:
                log.warning("Couldn't look %s by %s up on Spotify: %s", title, artist, error)
                return None
            for track in found.tracks:
                if same_artist(artist, track.artists) and (explicit or not track.explicit):
                    return track
        return None
