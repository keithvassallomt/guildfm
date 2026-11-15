"""AI radio: stations whose songs the AI picks, found on Spotify by name.

A station on as the source keeps a few songs picked ahead. When it runs low, GuildFM asks the AI
for another batch, from the station's description and what has played lately (and the time,
weather and music news, with global awareness on), then finds each on Spotify. A station rests a
song for a week: anything heard in the office in that time, lined up or queued, in any version
(see songs.py), is left out, and the AI is shown all of those so it can pick around them. If too
many of its picks are left out anyway, it's asked once more, told which. Explicit songs are left
out while that's turned off. Votes never reach the AI, so a station's taste stays its own. With
jingles to play, the AI also marks the odd song to have an ident before it (see jingles.py).

A station with a show coming up in a line-up picks its first songs a few minutes ahead and keeps
them until it comes on, so the show starts without waiting for the AI.

When the AI can't pick (OpenAI or Spotify is down, or out of credit), the station carries on with
songs heard before, the longest unheard first, so the music doesn't stop, and the AI is asked
again when those run low.

The AI picks station, which GuildFM keeps itself, follows whatever has been playing. It takes
over when the queue runs out, unless the settings say otherwise.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.ai import AIClient, AIError, Usage, object_schema
from guildfm.awareness import Awareness
from guildfm.jingles import kinds, playable
from guildfm.models import PickNote, Play, QueueEntry, Station, StationKind, Track
from guildfm.playlists import best_voted, current_source, tracks_of
from guildfm.prefs import get_pref
from guildfm.songs import plain, song_key, song_line
from guildfm.spotify import SpotifyBusy, SpotifyClient, SpotifyError, SpotifyTrack, remember

log = logging.getLogger(__name__)

LOW = 3  # songs left in a station's order before another batch is picked
BATCH = 8  # songs added at a time
SPARE = 8  # songs asked for on top, since some were heard lately or aren't on Spotify
REST_DAYS = 7  # a station doesn't pick a song heard in the office this many days back, or today
KEPT_TAKEN = 5  # songs already taken that stay in the order, for give_back
RECENT_PLAYS = 30  # recent plays shown to the AI, to follow on from
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
    "best-known title and main artist. Vary the artists, and don't pick a song more than once. "
    "The office hears this station every day, so look past the most obvious hits: mix "
    "well-known songs with others that fit just as well."
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


def same_artist(wanted: str, found: str) -> bool:
    wanted, found = plain(wanted), plain(found)
    return bool(wanted) and (wanted in found or found in wanted)


def _rest_start(now: float, zone: ZoneInfo, hours: float) -> float:
    """When a station's week of rest starts: midnight a week ago, so the songs the AI is shown
    drop off a whole day at a time. Never later than "recently played" reaches back."""
    midnight = datetime.fromtimestamp(now, zone).replace(hour=0, minute=0, second=0, microsecond=0)
    return min((midnight - timedelta(days=REST_DAYS)).timestamp(), now - hours * 3600)


async def _heard_since(db: AsyncSession, since: float) -> list[Track]:
    """Songs played since `since`, each once whatever the version, in the order first played."""
    plays = await db.scalars(
        select(Play).where(Play.played_at >= since).order_by(Play.played_at, Play.id)
    )
    heard: dict[str, Track] = {}
    for play in plays.unique():
        heard.setdefault(song_key(play.track), play.track)
    return list(heard.values())


async def _coming(db: AsyncSession) -> list[Track]:
    """Songs about to play: the queue, and what a station that's on has lined up."""
    ids = list(await db.scalars(select(QueueEntry.track_id)))
    source = await current_source(db)
    if source and source.station_id is not None:
        ids += source.order[source.cursor :]
    found = {track.id: track for track in await db.scalars(select(Track).where(Track.id.in_(ids)))}
    return [found[track_id] for track_id in dict.fromkeys(ids) if track_id in found]


async def _known(db: AsyncSession, title: str, artist: str, explicit: bool) -> SpotifyTrack | None:
    """A song GuildFM has found on Spotify before, by its exact title and the same artist.
    Where there are several versions, the one played most, then the one found most lately."""
    plays = select(func.count(Play.id)).where(Play.track_id == Track.id).scalar_subquery()
    found = await db.scalars(
        select(Track)
        .where(func.lower(Track.title) == title.strip().lower())
        .order_by(plays.desc(), Track.updated_at.desc())
    )
    for track in found:
        if same_artist(artist, track.artists) and (explicit or not track.explicit):
            return SpotifyTrack(
                id=track.id,
                title=track.title,
                artists=track.artists,
                album=track.album,
                duration_ms=track.duration_ms,
                explicit=track.explicit,
                art_url=track.art_url,
            )
    return None


@dataclass(frozen=True)
class Taste:
    """What picking songs needs to know about a station, saved or not."""

    name: str
    brief: str
    aware: bool  # global awareness
    idents: tuple[str, ...] = ()  # the kinds of jingle it can play: "system", "station"

    @classmethod
    def of(cls, station: Station, idents: tuple[str, ...] = ()) -> Taste:
        return cls(station.name, station.description, station.global_awareness, idents)


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
        self._preparing: asyncio.Task | None = None  # picking ahead of a show
        self._failed_at: dict[int, float] = {}  # station id: when a batch last found nothing
        # Run after a batch is added, so the queue can line the first one up.
        self.on_picked: list[Callable[[], Awaitable[None]]] = []

    def now(self) -> datetime:
        return self._clock()

    async def close(self) -> None:
        """Stop picking, before the database closes."""
        tasks = [task for task in (self._task, self._preparing) if task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def settle(self) -> None:
        """Wait for a batch that's being picked. For tests."""
        for task in (self._task, self._preparing):
            if task:
                await task

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
        except SpotifyBusy as error:
            log.warning("Not picking songs for a station while Spotify is paused: %s", error)
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
        chosen = await self.candidates(taste, BATCH)
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
            await self._keep_notes(db, chosen)
            await db.commit()
        return len(chosen)

    async def _keep_notes(self, db: AsyncSession, chosen: list[Pick]) -> None:
        """Why each was picked and any ident before it, kept so they survive a restart."""
        now = self._clock().timestamp()
        for pick in chosen:
            await db.merge(
                PickNote(track_id=pick.track.id, note=pick.note, ident=pick.ident, picked_at=now)
            )
        newest = select(PickNote.track_id).order_by(PickNote.picked_at.desc()).limit(NOTES_KEPT)
        await db.execute(delete(PickNote).where(PickNote.track_id.not_in(newest)))

    def prepare(self, station_id: int) -> None:
        """Pick a station's first songs ahead of its show in a line-up, in the background, unless
        it has some waiting already."""
        if self._preparing is None or self._preparing.done():
            self._preparing = asyncio.create_task(self._prepare(station_id))

    async def _prepare(self, station_id: int) -> None:
        try:
            async with self._sessions() as db:
                station = await db.get(Station, station_id)
                if station is None or station.ready:
                    return
                idents = kinds(await playable(db, station_id)) if station.jingles else ()
                taste = Taste.of(station, idents)
            chosen = await self.candidates(taste, BATCH)
            if not chosen:
                return
            async with self._sessions() as db:
                await remember(db, [pick.track for pick in chosen])
                station = await db.get(Station, station_id)
                if station is None:
                    return
                station.ready = [pick.track.id for pick in chosen]
                await self._keep_notes(db, chosen)
                await db.commit()
            log.info("%s picked its first songs ahead of its show", taste.name)
        except (AIError, SpotifyBusy) as error:
            log.warning("A station couldn't pick ahead of its show: %s", error)
        except Exception:
            log.exception("Picking ahead of a show failed")

    async def replay(self, station_id: int) -> int:
        """For when the AI can't pick: songs heard before, so the music carries on. Songs the
        station has played, then Best Voted, each the longest unheard first. Anything played
        lately (in any version), queued, lined up, or explicit while that's turned off is left
        out, as ever. Returns how many were added."""
        async with self._sessions() as db:
            station = await db.get(Station, station_id)
            source = await current_source(db)
            if station is None or source is None or source.station_id != station_id:
                return 0
            since = time.time() - await get_pref(db, "recently_played_hours") * 3600
            explicit = await get_pref(db, "allow_explicit")
            lately = await _heard_since(db, since) + await _coming(db)
            avoid = {song_key(track) for track in lately}
            last_heard: dict[str, float] = {}
            rows = await db.execute(
                select(Track, func.max(Play.played_at))
                .join(Play, Play.track_id == Track.id)
                .group_by(Track.id)
            )
            for track, played_at in rows.all():
                key = song_key(track)
                last_heard[key] = max(played_at, last_heard.get(key, 0.0))
            played_here = select(Play.track_id).where(Play.station_id == station_id)
            own = list(await db.scalars(select(Track).where(Track.id.in_(played_here))))
            favourites = [entry.track for entry in await tracks_of(db, (await best_voted(db)).id)]
            chosen: list[str] = []
            for pool in (own, favourites):
                fresh: dict[str, str] = {}  # one version of each song
                for track in pool:
                    key = song_key(track)
                    if key not in avoid and key not in fresh and (explicit or not track.explicit):
                        fresh[key] = track.id
                longest_unheard = sorted(fresh, key=lambda key: last_heard.get(key, 0.0))
                chosen += [fresh[key] for key in longest_unheard[: BATCH - len(chosen)]]
                avoid |= set(fresh)
            if not chosen:
                return 0
            keep = max(0, source.cursor - KEPT_TAKEN)
            source.order = source.order[keep:] + chosen
            source.cursor -= keep
            await db.commit()
        log.warning("%s is playing songs from before until the AI can pick again", station.name)
        return len(chosen)

    async def candidates(self, taste: Taste, count: int) -> list[Pick]:
        """Up to `count` songs for a station like `taste`, found on Spotify, in the order the
        AI wants them played, each with why it fits and any ident to play before it. Anything
        heard in the office this past week, lined up or queued, in any version, is left out.
        The AI is shown all of those, and is asked once more if too many of its picks are left
        out anyway. Nothing is saved. While Spotify has GuildFM paused, raises SpotifyBusy
        without asking the AI, since most of what it picks couldn't be looked up."""
        self._spotify.not_paused()
        async with self._sessions() as db:
            explicit = await get_pref(db, "allow_explicit")
            zone = ZoneInfo(await get_pref(db, "timezone"))
            location = await get_pref(db, "weather_location")
            hours = await get_pref(db, "recently_played_hours")
            heard = await _heard_since(db, _rest_start(time.time(), zone, hours))
            coming = await _coming(db)
            recent = (
                await db.scalars(select(Play).order_by(Play.id.desc()).limit(RECENT_PLAYS))
            ).unique()
            plays = [song_line(play.track) for play in recent]
        avoid = {song_key(track) for track in heard + coming}

        context = None
        if taste.aware:
            context = await self._awareness.context(location, self._clock().astimezone(zone))
        prompt = self._prompt(taste, explicit, heard, coming, context, plays)
        instructions = INSTRUCTIONS.format(name=taste.name)
        schema = picks_schema(taste.idents)

        chosen: list[Pick] = []
        refused: list[str] = []  # heard this week or lined up, or suggested twice
        unfound: list[str] = []  # not on Spotify, or explicit while that's turned off
        suggested, asks, usage = 0, 0, Usage()
        while asks < 2 and len(chosen) < count and not (asks and self._spotify.paused):
            asks += 1
            asked = count - len(chosen) + SPARE
            ask = self._ask_for(asked, chosen, refused, unfound)
            answer = await self._ai.json(instructions, f"{prompt}\n\n{ask}", "picks", schema, usage)
            songs = answer.get("songs", [])[:asked]
            suggested += len(songs)
            for song, track in zip(songs, await self._find_all(songs, explicit), strict=True):
                said = f"{song.get('artist', '')} – {song.get('title', '')}"
                if track is None:
                    unfound.append(said)
                elif (key := song_key(track)) in avoid:
                    refused.append(said)
                elif len(chosen) < count:
                    avoid.add(key)
                    ident = song.get("ident")
                    ident = ident if ident in taste.idents else None
                    chosen.append(Pick(track, song.get("note", ""), ident))
        log.info(
            "%s: %d of the AI's %d picks kept, %d heard this week or lined up, %d not on Spotify"
            "%s. Tokens: %s in (%s cached), %s out",
            taste.name,
            len(chosen),
            suggested,
            len(refused),
            len(unfound),
            ", after asking again" if asks > 1 else "",
            f"{usage.input:,}",
            f"{usage.cached:,}",
            f"{usage.output:,}",
        )
        return chosen

    @staticmethod
    def _prompt(
        taste: Taste,
        explicit: bool,
        heard: list[Track],
        coming: list[Track],
        context: str | None,
        plays: list[str],
    ) -> str:
        """Everything but how many to pick. What changes least comes first, so most of the
        prompt starts the same from one batch to the next and OpenAI bills that part at its
        cached rate: through the day, the week's songs only grow at the end."""
        parts = [f"Station brief: {taste.brief}"]
        if not explicit:
            parts.append("Don't pick explicit songs.")
        if taste.idents:
            parts.append(
                "Idents are short jingles played in the pause before a song. Mark the odd song to "
                "have one, about one in four, where it helps the flow: at a change of mood or "
                "pace, or to start a new run of songs. Never two songs in a row. The kinds: "
                + "; ".join(IDENTS[kind] for kind in taste.idents)
                + "."
            )
        if heard:
            parts.append(
                "Heard in the office this past week, oldest first. Don't pick any of these, in "
                "any version:\n" + "\n".join(song_line(track) for track in heard)
            )
        if coming:
            parts.append(
                "Lined up to play. Don't pick these either:\n"
                + "\n".join(song_line(track) for track in coming)
            )
        if context:
            parts.append(
                f"Let this steer the picks where it fits, without overdoing it:\n{context}"
            )
        if plays:
            parts.append("Played lately, newest first, to follow on from:\n" + "\n".join(plays))
        return "\n\n".join(parts)

    @staticmethod
    def _ask_for(asked: int, chosen: list[Pick], refused: list[str], unfound: list[str]) -> str:
        """How many to pick, and the first time round's picks when asking again."""
        if not (chosen or refused or unfound):
            return f"Pick {asked} songs, in the order they should play."
        parts = []
        if chosen:
            parts.append(
                "Your picks so far, which are in:\n"
                + "\n".join(song_line(pick.track) for pick in chosen)
            )
        if refused:
            parts.append(
                "These are out, as they've been heard this week or are lined up:\n"
                + "\n".join(refused)
            )
        if unfound:
            parts.append("These couldn't be found on Spotify:\n" + "\n".join(unfound))
        then = "to play after your picks so far" if chosen else "in the order they should play"
        parts.append(f"Pick {asked} more songs, different from all of these, {then}.")
        return "\n\n".join(parts)

    async def _find_all(
        self, songs: list[dict[str, Any]], explicit: bool
    ) -> list[SpotifyTrack | None]:
        """Each song from GuildFM's own records if it's been found before, otherwise from
        Spotify. Searching Spotify less keeps GuildFM under its rate limit."""
        async with self._sessions() as db:
            known = [
                await _known(db, song.get("title", ""), song.get("artist", ""), explicit)
                for song in songs
            ]
        searches = asyncio.Semaphore(SEARCHES)

        async def find(song: dict[str, Any], track: SpotifyTrack | None) -> SpotifyTrack | None:
            if track:
                return track
            async with searches:
                return await self._find(song.get("title", ""), song.get("artist", ""), explicit)

        return list(await asyncio.gather(*(find(s, t) for s, t in zip(songs, known, strict=True))))

    async def _find(self, title: str, artist: str, explicit: bool) -> SpotifyTrack | None:
        """The song on Spotify: by title and artist, then more loosely. The artist has to match
        either way, so a cover or a karaoke version doesn't slip in."""
        for query in (f'track:"{title}" artist:"{artist}"', f"{title} {artist}"):
            try:
                found = await self._spotify.search(query)
            except SpotifyBusy:
                return None  # said once already, when Spotify paused GuildFM
            except SpotifyError as error:
                log.warning("Couldn't look %s by %s up on Spotify: %s", title, artist, error)
                return None
            for track in found.tracks:
                if same_artist(artist, track.artists) and (explicit or not track.explicit):
                    return track
        return None
