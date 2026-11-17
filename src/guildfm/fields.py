"""The named fields a talk station's script prompt can use, such as [news] or [weather], and
what's behind each, for its DJs to talk about. Only the fields a prompt uses are gathered.

[news], [sports] and [celebrities] are looked up on the web by the AI and kept a while, through
Global Awareness (awareness.py), which also has the weather where the office is for [weather].
[lineup] and [djs] come from the database: what's on for the rest of the day, and GuildFM's
other DJs."""

import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.awareness import Awareness
from guildfm.models import DJProfile, LineupSlot, Station, StationDJ
from guildfm.playlists import current_source

# Each field, with what it brings in, as the station editor lists them.
FIELDS = {
    "news": "Light, odd and funny stories",
    "weather": "The weather where the office is",
    "sports": "British football: news, scores and results",
    "celebrities": "Birthdays, anniversaries and news",
    "lineup": "What's on for the rest of the day",
    "djs": "GuildFM's other DJs",
}
FROM_THE_WEB = ("news", "sports", "celebrities")  # topics in awareness.TOPICS
_FIELD = re.compile(r"\[(" + "|".join(FIELDS) + r")\]", re.IGNORECASE)


def used(prompt: str) -> list[str]:
    """The fields `prompt` uses, in the order FIELDS has them."""
    found = {name.lower() for name in _FIELD.findall(prompt)}
    return [name for name in FIELDS if name in found]


def prime(awareness: Awareness, prompt: str, now: datetime) -> None:
    """Starts looking up the web fields `prompt` uses, so they're in by the time they're
    needed: they can take a minute or so."""
    for name in used(prompt):
        if name in FROM_THE_WEB:
            awareness.gathered(name, now.date())


async def material(
    db: AsyncSession,
    awareness: Awareness,
    station: Station,
    location: str,
    now: datetime,
    wait: float = 0,
) -> dict[str, str]:
    """What's behind each field the station's script prompt uses, by field, for its DJs. A
    field with nothing in yet is left out; `wait` is how many seconds to wait for the web
    fields still being looked up. `now` is in the office's time zone."""
    names = used(station.script_prompt)
    web = [name for name in names if name in FROM_THE_WEB]
    if web and wait:
        await awareness.ready(web, now.date(), wait)
    found = {}
    for name in names:
        if name in FROM_THE_WEB:
            text = awareness.gathered(name, now.date())
        elif name == "weather":
            weather = await awareness.weather(location)
            text = weather and f"Right now in {location}: {weather}."
        elif name == "lineup":
            text = await _lineup(db, now)
        else:
            text = await _djs(db, station)
        if text:
            found[name] = text.strip()
    return found


def _listed(names: list[str]) -> str:
    return names[0] if len(names) < 2 else f"{', '.join(names[:-1])} and {names[-1]}"


def _slot(slot: LineupSlot) -> str:
    if slot.playlist:
        return f"the playlist {slot.playlist.name}"
    station = slot.station
    kind = "talk show" if station.talk_station else "show"
    names = [dj.name for dj in station.hosts]
    with_djs = f", with {_listed(names)}" if names else ""
    return f"{station.name}, a {kind}{with_djs}"


async def _lineup(db: AsyncSession, now: datetime) -> str:
    """The rest of today's line-up, from what's on now."""
    # Here, not at the top: line-ups need the radio, which primes these fields for a show.
    from guildfm.lineups import clock, minute_of

    source = await current_source(db)
    lineup = source.lineup if source else None
    if lineup is None:
        return "No line-up is on today."
    minute = minute_of(now)
    later = [slot for slot in lineup.slots if slot.end > minute]
    if not later:
        return f"Today's line-up, {lineup.name}, has finished for the day."
    lines = [f"- {clock(slot.start)} to {clock(slot.end)}: {_slot(slot)}" for slot in later]
    return f"The rest of today's line-up, {lineup.name}:\n" + "\n".join(lines)


async def _djs(db: AsyncSession, station: Station) -> str:
    """GuildFM's DJs besides the station's own: who they are, what they host, and their hooks."""
    own = {dj.id for dj in station.hosts}
    hosting = await db.execute(
        select(StationDJ.dj_id, Station.name)
        .join(Station, Station.id == StationDJ.station_id)
        .order_by(func.lower(Station.name))
    )
    hosts: dict[int, list[str]] = {}
    for dj_id, name in hosting:
        hosts.setdefault(dj_id, []).append(name)
    everyone = await db.scalars(select(DJProfile).order_by(func.lower(DJProfile.name)))
    lines = []
    for dj in everyone:
        if dj.id in own:
            continue
        about = [f"{dj.name}."]
        if dj.personality:
            about.append(dj.personality)
        if dj.id in hosts:
            about.append(f"Hosts {_listed(hosts[dj.id])}.")
        if dj.pet_peeves:
            about.append(f"Pet peeves: {dj.pet_peeves}")
        if dj.soft_spots:
            about.append(f"Soft spots: {dj.soft_spots}")
        if dj.obsession:
            about.append(f"Keeps coming back to: {dj.obsession}")
        lines.append("- " + " ".join(about))
    if not lines:
        return "There are no other DJs at GuildFM."
    return "GuildFM's other DJs:\n" + "\n".join(lines)
