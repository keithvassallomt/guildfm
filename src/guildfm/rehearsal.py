"""An hour of a station, worked out in advance to look over: the songs the AI would pick, the
jingles, and what the DJ would say around them, with the same picking, jingle rules and DJ as the
real thing.

Nothing is kept. The station's picks, the queue and the speakers are left as they were, so the
real hour will differ, not least because requests play first.
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from guildfm.ai import AIClient
from guildfm.announcements import GAP_SECONDS
from guildfm.awareness import Awareness, clock_line
from guildfm.dj import RECENT_LINES, Persona, Song, due, write_line
from guildfm.jingles import Rotation, kinds, playable
from guildfm.models import EntryState, Jingle, Station
from guildfm.prefs import get_pref
from guildfm.queue import in_state
from guildfm.radio import Radio, Taste
from guildfm.spotify import SpotifyTrack

HOUR = 60 * 60
ASKED = 20  # songs asked for: enough for an hour of most music


@dataclass(frozen=True)
class Slot:
    """A song in the hour, with the jingle and what the DJ says before it, if anything."""

    track: SpotifyTrack
    note: str  # why the AI picked it
    starts_at: datetime
    line: str | None
    jingle: Jingle | None = None


async def rehearse(
    sessionmaker,
    radio: Radio,
    ai: AIClient,
    awareness: Awareness,
    station,  # a saved Station or the editor's form: the same fields either way
    station_id: int | None,
) -> list[Slot]:
    """An hour of `station`, starting now. A saved station's recent picks are left out, as
    they would be for real."""
    async with sessionmaker() as db:
        saved = await db.get(Station, station_id) if station_id else None
        playing = await in_state(db, EntryState.PLAYING)
        before = playing and Song(playing.track.title, playing.track.artists)
        zone = ZoneInfo(await get_pref(db, "timezone"))
        location = await get_pref(db, "weather_location")
        jingles = await playable(db, station_id) if station.jingles else []
    taste = Taste(
        station.name,
        station.description,
        station.global_awareness,
        saved.picked if saved else [],
        kinds(jingles),
    )
    found = await radio.candidates(taste, ASKED)
    rotation = Rotation()

    now = radio.now()
    persona = Persona.of(station)
    said: deque[str] = deque(maxlen=RECENT_LINES)
    # As for real: the DJ talks on the first song, then as often as the station says.
    songs, last = station.talk_every - 1, float("-inf")
    elapsed = 0.0
    slots = []
    for pick in found:
        track, note = pick.track, pick.note
        if elapsed >= HOUR:
            break
        jingle = rotation.next(pick.ident, jingles)
        if jingle:
            elapsed += jingle.seconds + GAP_SECONDS
        starts_at = (now + timedelta(seconds=elapsed)).astimezone(zone)
        line = None
        if station.dj:
            songs += 1
            if due(songs, (elapsed - last) / 60, station.talk_every, station.talk_unit):
                if station.global_awareness:
                    context = await awareness.context(location, starts_at)
                else:
                    context = clock_line(starts_at)
                up_next = f"Up next: {Song(track.title, track.artists)}."
                if note:
                    up_next += f" Why it was picked: {note}"
                script = await write_line(
                    ai,
                    persona,
                    context,
                    before,
                    up_next,
                    [],
                    list(said),
                    aware=station.global_awareness,
                )
                said.append(script)
                songs, last = 0, elapsed
                line = script or None
        slots.append(Slot(track, note, starts_at, line, jingle))
        before = Song(track.title, track.artists)
        elapsed += track.duration_ms / 1000
    return slots
