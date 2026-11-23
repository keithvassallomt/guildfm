"""Fresh hooks: a talk show DJ's pet peeves, soft spots and running obsession, rewritten by the AI
one at a time, so each lasts about a month and the same stories don't come round for ever.

Each night between midnight and six, office time, a DJ who hosts a talk station and has fresh
hooks on gets one hook rewritten at most: a blank one first, then the oldest, once it's
HOOK_DAYS old. The hook it replaces goes among their old ones, which the AI is told, so none
comes back. A hook changed by hand starts its month again (api/stations.py)."""

import logging
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from guildfm.ai import AIClient, AIError, object_schema
from guildfm.models import DJProfile, Station, StationDJ
from guildfm.prefs import get_pref
from guildfm.talk import HOOKS

log = logging.getLogger(__name__)

DAY = 24 * 60 * 60
HOOK_DAYS = 30  # how long a hook lasts before it's rewritten
OLD_KEPT = 30  # old hooks kept, for the AI not to bring back
NIGHT_ENDS = 6  # hooks are rewritten from midnight until this hour, office time
LIMITS = {"pet_peeves": 300, "soft_spots": 300, "obsession": 200}
NAMES = {"pet_peeves": "pet peeves", "soft_spots": "soft spots", "obsession": "running obsession"}
GUIDES = {
    "pet_peeves": "two or three small, everyday things that wind them up, a short sentence "
    "each, such as: People who reply-all to say thanks. Lukewarm tea.",
    "soft_spots": "two or three things they go soft on, a short sentence each, such as: A "
    "proper chip butty. Power ballads at a work do.",
    "obsession": "one thing they'll keep coming back to for the next month, with somewhere to "
    "go: a mystery, a project, a rivalry or a quest, in a sentence or two, such as: Building a "
    "shed. Has been for eleven years.",
}

INSTRUCTIONS = """You write hooks for the DJs on an office radio station's talk shows, in the \
UK: things about a DJ that the shows bring up now and then. Pet peeves are what the other DJs \
can wind them up about. Soft spots are what they go soft on. A running obsession is a storyline \
they keep coming back to for a month, so it needs somewhere to go.

Make it specific, everyday and funny, and right for who the DJ is: office life, home, hobbies, \
food, the commute, the neighbours. Nothing about politics, religion, real people, or anything \
sad. Never one of the examples you're given, and never one of their old hooks or anything like \
it. British English, plain words, no lists, no dashes."""

HOOK = object_schema(hook={"type": "string"})


def due(dj: DJProfile, now: float) -> str | None:
    """The hook due to be rewritten now, if any: a blank one first, then the oldest once it's
    HOOK_DAYS old. A hook with no age is as old as can be."""
    blank = [hook for hook in HOOKS if not getattr(dj, hook).strip()]
    if blank:
        return blank[0]
    at = dj.hooks_at or {}
    oldest = min(HOOKS, key=lambda hook: at.get(hook, 0))
    return oldest if now - at.get(oldest, 0) >= HOOK_DAYS * DAY else None


def next_fresh(dj: DJProfile, now: float, zone: ZoneInfo) -> tuple[str, date]:
    """Which hook is rewritten next, and the morning it's new by: the first night, from
    midnight to six, once it's due."""
    blank = [hook for hook in HOOKS if not getattr(dj, hook).strip()]
    if blank:
        hook, when = blank[0], now
    else:
        at = dj.hooks_at or {}
        hook = min(HOOKS, key=lambda name: at.get(name, 0))
        when = max(now, at.get(hook, 0) + HOOK_DAYS * DAY)
    moment = datetime.fromtimestamp(when, zone)
    morning = moment.date() if moment.hour < NIGHT_ENDS else moment.date() + timedelta(days=1)
    return hook, morning


def changed_hooks(
    dj: DJProfile, hooks: dict[str, str], now: float
) -> tuple[dict[str, float], list[str]]:
    """When each of the DJ's hooks was written, and their old hooks, once `hooks` are saved
    over the ones they have: a hook changed by hand starts its month again, and the one it
    replaces is kept, so the AI doesn't bring it back."""
    at = dict(dj.hooks_at or {})
    old = list(dj.old_hooks or [])
    for hook, text in hooks.items():
        before = (getattr(dj, hook) or "").strip()
        if text == before:
            continue
        if before:
            old.append(before)
        if text:
            at[hook] = now
        else:
            at.pop(hook, None)
    return at, old[-OLD_KEPT:]


async def write_hook(ai: AIClient, dj: DJProfile, hook: str) -> str:
    """A new `hook` for `dj`, written by the AI, unlike any they've had. Raises AIError if it
    can't be had."""
    parts = [f"The DJ: {dj.name}. {dj.personality or 'No personality given.'}"]
    keeping = [
        f"{NAMES[other].capitalize()}: {getattr(dj, other)}"
        for other in HOOKS
        if other != hook and getattr(dj, other).strip()
    ]
    if keeping:
        parts.append("Their other hooks, which stay as they are:\n" + "\n".join(keeping))
    old = [*(dj.old_hooks or []), getattr(dj, hook).strip()]
    old = [text for text in old if text]
    if old:
        parts.append(
            "Hooks they've had before. Don't bring back any of these, or anything like them:\n"
            + "\n".join(f"- {text}" for text in old)
        )
    parts.append(
        f"Write {dj.name}'s new {NAMES[hook]}: {GUIDES[hook]} Under {LIMITS[hook]} characters."
    )
    answer = await ai.json(INSTRUCTIONS, "\n\n".join(parts), "dj_hook", HOOK)
    return str(answer.get("hook", "")).strip()[: LIMITS[hook]]


async def freshen(sessionmaker, ai: AIClient, now: float) -> list[str]:
    """One hook rewritten for each DJ who hosts a talk station, has fresh hooks on and has one
    due. Returns what changed, as lines for the journal."""
    changed = []
    async with sessionmaker() as db:
        hosting = (
            select(StationDJ.dj_id)
            .join(Station, Station.id == StationDJ.station_id)
            .where(Station.talk_station.is_(True))
        )
        djs = await db.scalars(
            select(DJProfile)
            .where(DJProfile.id.in_(hosting), DJProfile.fresh_hooks.is_(True))
            .order_by(DJProfile.id)
        )
        for dj in djs.all():
            hook = due(dj, now)
            if hook is None:
                continue
            try:
                text = await write_hook(ai, dj, hook)
            except AIError as error:
                log.warning("Couldn't write %s's new %s: %s", dj.name, NAMES[hook], error)
                continue
            if not text:
                continue
            dj.hooks_at, dj.old_hooks = changed_hooks(dj, {hook: text}, now)
            setattr(dj, hook, text)
            changed.append(f"{dj.name}'s new {NAMES[hook]}: {text}")
        await db.commit()
    return changed


class FreshHooks:
    """Rewrites DJs' hooks once a night, from Housekeeping's hourly tick."""

    def __init__(self, sessionmaker, ai: AIClient) -> None:
        self._sessions = sessionmaker
        self._ai = ai
        self._done_on: date | None = None  # the night it last ran, by its morning's date

    async def tick(self, now: float) -> None:
        async with self._sessions() as db:
            zone = ZoneInfo(await get_pref(db, "timezone"))
        moment = datetime.fromtimestamp(now, zone)
        if moment.hour >= NIGHT_ENDS or self._done_on == moment.date():
            return
        self._done_on = moment.date()
        for line in await freshen(self._sessions, self._ai, now):
            log.info("%s", line)


def hooks_of(dj: Any) -> dict[str, str]:
    """A DJ's hooks, by name, from a form or a profile."""
    return {hook: (getattr(dj, hook) or "").strip() for hook in HOOKS}
