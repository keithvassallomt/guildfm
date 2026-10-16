"""Global awareness for stations: the weather where the office is and the music news, so the AI
can steer its picks and the DJ has something to talk about. Both are kept for a while, so
stations don't ask again for every song. The news takes up to a minute to gather, longer than
the DJ has, so it's gathered in the background and used once it's in."""

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime

import httpx2

from guildfm.ai import AIClient, AIError

log = logging.getLogger(__name__)

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
# The weather is fetched while a DJ line is being written, so it can't hold that up for long.
WEATHER_TIMEOUT = 5
WEATHER_SECONDS = 20 * 60
NEWS_SECONDS = 6 * 60 * 60
FAILED_SECONDS = 10 * 60  # after a failure, how long before asking again

# WMO weather codes, as Open-Meteo reports them.
WEATHER_WORDS = {
    0: "clear skies", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog",
    48: "freezing fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle", 61: "light rain", 63: "rain",
    65: "heavy rain", 66: "freezing rain", 67: "freezing rain", 71: "light snow", 73: "snow",
    75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers",
    82: "heavy showers", 85: "snow showers", 86: "heavy snow showers", 95: "thunderstorms",
    96: "thunderstorms with hail", 99: "thunderstorms with hail",
}  # fmt: skip
# What people write in a location, and the country code Open-Meteo gives.
COUNTRIES = {"uk": "gb", "united kingdom": "gb", "britain": "gb", "great britain": "gb"}

NEWS_INSTRUCTIONS = "You keep the DJs of an office radio station in the UK up to date."
NEWS_PROMPT = (
    "Search the web for music news from the last few days that a radio DJ might mention, or that "
    "could steer which songs to play: deaths of well-known musicians, award and song contest "
    "winners, big anniversaries, notable releases and tours. Give at most five short, factual "
    "bullet points, each with its date, in plain text with no links or formatting. Leave out "
    "gossip. If nothing notable happened, say so."
)


def part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 14:
        return "lunchtime"
    if 14 <= hour < 17:
        return "afternoon"
    return "evening" if 17 <= hour < 22 else "night"


def clock_line(now: datetime) -> str:
    """ "It's Friday 16 October, 12:40, lunchtime." In the office's time zone."""
    return f"It's {now:%A} {now.day} {now:%B}, {now:%H:%M}, {part_of_day(now.hour)}."


class Awareness:
    def __init__(
        self,
        ai: AIClient,
        http: httpx2.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ai = ai
        self._http = http or httpx2.AsyncClient(timeout=WEATHER_TIMEOUT)
        self._clock = clock
        self._places: dict[str, tuple[float, float] | None] = {}
        self._weather: dict[str, tuple[float, str | None]] = {}  # when it was read, and what
        self._news: tuple[float, str | None] | None = None
        self._gathering: asyncio.Task | None = None

    async def close(self) -> None:
        if self._gathering:
            self._gathering.cancel()
            await asyncio.gather(self._gathering, return_exceptions=True)
        await self._http.aclose()

    async def _place(self, location: str) -> tuple[float, float] | None:
        """Where `location` is, such as "Carlisle, Cumbria, UK". The search takes a place name,
        so the rest of the location picks between places with that name."""
        if location not in self._places:
            name, *rest = [part.strip().lower() for part in location.split(",") if part.strip()]
            response = await self._http.get(
                GEOCODE, params={"name": name, "count": 10, "language": "en"}
            )
            response.raise_for_status()
            results = response.json().get("results") or []

            def fit(result: dict) -> int:
                fields = {
                    str(result.get(key) or "").lower()
                    for key in ("admin1", "admin2", "admin3", "country", "country_code")
                }
                return sum(COUNTRIES.get(part, part) in fields for part in rest)

            best = max(results, key=fit, default=None)  # the first of the best fits
            self._places[location] = best and (best["latitude"], best["longitude"])
        return self._places[location]

    async def weather(self, location: str) -> str | None:
        """The weather at `location` now, in words, or None if it can't be had."""
        kept = self._weather.get(location)
        if kept and self._clock() - kept[0] < (WEATHER_SECONDS if kept[1] else FAILED_SECONDS):
            return kept[1]
        words = None
        try:
            place = await self._place(location)
            if place:
                response = await self._http.get(
                    FORECAST,
                    params={
                        "latitude": place[0],
                        "longitude": place[1],
                        "current": "temperature_2m,apparent_temperature,weather_code,"
                        "wind_speed_10m,is_day",
                    },
                )
                response.raise_for_status()
                now = response.json()["current"]
                sky = WEATHER_WORDS.get(now["weather_code"], "unsettled")
                light = "daylight" if now["is_day"] else "dark"
                words = (
                    f"{sky}, {round(now['temperature_2m'])}°C, feels like "
                    f"{round(now['apparent_temperature'])}°C, wind "
                    f"{round(now['wind_speed_10m'])} km/h, {light}"
                )
        except (httpx2.HTTPError, KeyError, ValueError) as error:
            # An expected hiccup, tried again later, so one line rather than a traceback.
            log.warning("Couldn't get the weather for %s (%s)", location, type(error).__name__)
        self._weather[location] = (self._clock(), words)
        return words

    def news(self) -> str | None:
        """A few lines of recent music news, or None if there's none in yet. When it's out of
        date, fresh news is gathered in the background for next time."""
        kept = self._news
        fresh = kept and self._clock() - kept[0] < (NEWS_SECONDS if kept[1] else FAILED_SECONDS)
        if not fresh and not (self._gathering and not self._gathering.done()):
            self._gathering = asyncio.create_task(self.gather_news())
        return kept[1] if kept else None

    async def gather_news(self) -> None:
        try:
            text = await self._ai.text(NEWS_INSTRUCTIONS, NEWS_PROMPT, web_search=True)
        except AIError as error:
            log.warning("Couldn't get the music news: %s", error)
            text = None
        # Stale news beats none while the next lot is gathered.
        if text or not self._news:
            self._news = (self._clock(), text)
        else:
            self._news = (self._clock() - NEWS_SECONDS + FAILED_SECONDS, self._news[1])

    async def settle(self) -> None:
        """Wait for news being gathered. For tests."""
        if self._gathering:
            await self._gathering

    async def context(self, location: str, now: datetime) -> str:
        """The time, the weather and the news, for a prompt."""
        weather, news = await self.weather(location), self.news()
        lines = [clock_line(now)]
        if weather:
            lines.append(f"The weather in {location} right now: {weather}.")
        if news:
            lines.append(f"Recent music news:\n{news.strip()}")
        return "\n".join(lines)
