"""Admin settings, kept in the database. (config.py is different: it comes from .env.)"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.models import Setting

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# OpenAI's text-to-speech voices. Marin and Cedar sound the most natural.
VOICES = (
    "marin", "cedar", "alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx",
    "sage", "shimmer", "verse",
)  # fmt: skip

QUEUE_RUNS_OUT = ("restart_playlist", "default_station", "ai_pick")

DEFAULTS: dict[str, Any] = {
    "allow_explicit": True,
    "request_cap": 5,  # requests one person can have in the queue at once
    "downvote_threshold": -3,  # a request is removed when its score falls to this
    "recently_played_hours": 24,
    "best_voted_min_upvotes": 5,  # a track needs more than this many to join Best Voted
    "best_voted_size": 50,
    "queue_runs_out": "ai_pick",
    "default_station": None,  # a station id, for queue_runs_out "default_station"
    "schedule": {
        day: {"on": day not in ("sat", "sun"), "start": "08:00", "end": "18:00"} for day in DAYS
    },
    "timezone": "Europe/London",
    "weather_location": "Carlisle, Cumbria, UK",
    "announcement_voice": "cedar",
}


async def get_pref(db: AsyncSession, key: str) -> Any:
    row = await db.get(Setting, key)
    return row.value if row else DEFAULTS[key]


async def all_prefs(db: AsyncSession) -> dict[str, Any]:
    return {key: await get_pref(db, key) for key in DEFAULTS}


async def set_pref(db: AsyncSession, key: str, value: Any) -> None:
    if key not in DEFAULTS:
        raise KeyError(key)
    await db.merge(Setting(key=key, value=value))
    await db.commit()
