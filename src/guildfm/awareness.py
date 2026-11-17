"""Global awareness for stations: the weather where the office is and the music news, so the AI
can steer its picks and the DJ has something to talk about. Both are kept for a while, so
stations don't ask again for every song. The news takes up to a minute to gather, longer than
the DJ has, so it's gathered in the background and used once it's in.

Talk stations' DJs have more to talk about, gathered the same way when their script prompt asks
for it (fields.py): light news, British football, and celebrities' birthdays and news."""

import asyncio
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

import httpx2

from guildfm.ai import AIClient, AIError
from guildfm.health import Health

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
LIGHT_NEWS_PROMPT = (
    "Search the web for light news from the last day or two that two radio DJs could chat "
    "about: odd, funny, surprising or heart-warming stories, from the UK or anywhere. Leave out "
    "politics, elections, wars, crime, court cases, disasters, accidents, deaths, illness and "
    "anything else sad or divisive. Give at most five short, factual bullet points, each with "
    "its date and where it happened, in plain text with no links or formatting. If nothing "
    "suitable happened, say so."
)
FOOTBALL_PROMPT = (
    "Search the web for British football from the last few days: results and scores in the "
    "Premier League, the English Football League, the Scottish Premiership and the cups, and "
    "what people are talking about, such as a shock result, a manager leaving or a record. "
    "British clubs and the home nations only, and nothing but football. Leave out crime, court "
    "cases, abuse and serious injuries. Give at most six short, factual bullet points, each with "
    "its date, in plain text with no links or formatting. If there's been no football, say so."
)
CELEBRITIES_PROMPT = (
    "Today is {date}. Search the web for well-known people an office in the UK would know, such "
    "as musicians, actors, TV presenters and sports stars, whose birthday is today, and for "
    "anniversaries today of famous records, films, shows and events. Add any light celebrity "
    "news from the last few days. For a birthday, give the date of birth exactly as a reliable "
    "source has it, never an age. Leave out deaths, anniversaries of deaths, illness, scandal, "
    "break-ups and court cases. Give at most six short, factual bullet points in plain text with "
    "no links or formatting."
)


@dataclass(frozen=True)
class Topic:
    """Something the AI looks up on the web for the DJs."""

    prompt: str  # what to look for; {date} is today, such as "Monday 16 November 2026"
    seconds: float  # how long what it finds is kept
    daily: bool = False  # only good on the day it was found, such as today's birthdays


TOPICS = {
    "music": Topic(NEWS_PROMPT, NEWS_SECONDS),
    "news": Topic(LIGHT_NEWS_PROMPT, 6 * 60 * 60),
    "sports": Topic(FOOTBALL_PROMPT, 3 * 60 * 60),
    "celebrities": Topic(CELEBRITIES_PROMPT, 12 * 60 * 60, daily=True),
}


# A source the web search cites, as "([bbc.co.uk](https://...))", or a link, "[words](url)".
_CITED = re.compile(r"\s*\(\[[^\]]*\]\([^)]*\)\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def without_links(text: str) -> str:
    """What the web search found without the sources and links it adds, asked or not."""
    return _LINK.sub(r"\1", _CITED.sub("", text)).strip()


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
        # By topic: when it was found, what (None for nothing), and for a daily topic the day.
        self._found: dict[str, tuple[float, str | None, str]] = {}
        self._gathering: dict[str, asyncio.Task] = {}
        self.weather_health = Health()

    async def close(self) -> None:
        for task in self._gathering.values():
            task.cancel()
        await asyncio.gather(*self._gathering.values(), return_exceptions=True)
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
            self.weather_health.failed(f"Couldn't get the weather for {location}.")
        else:
            if words:
                self.weather_health.worked()
            else:
                self.weather_health.failed(f"Couldn't find {location} on the map.")
        self._weather[location] = (self._clock(), words)
        return words

    def news(self) -> str | None:
        """A few lines of recent music news, or None if there's none in yet. When it's out of
        date, fresh news is gathered in the background for next time."""
        return self.gathered("music")

    def gathered(self, topic: str, today: date | None = None) -> str | None:
        """What the AI found on `topic` (one of TOPICS), or None if nothing's in yet. When it's
        out of date, more is gathered in the background for next time. What's found on a daily
        topic is only good on `today`, the day it was found."""
        spec = TOPICS[topic]
        day = today.isoformat() if spec.daily and today else ""
        kept = self._found.get(topic)
        current = kept is not None and kept[2] == day
        keep_for = spec.seconds if current and kept[1] else FAILED_SECONDS
        fresh = current and self._clock() - kept[0] < keep_for
        running = self._gathering.get(topic)
        if not fresh and not (running and not running.done()):
            self._gathering[topic] = asyncio.create_task(self._gather(topic, today, day))
        return kept[1] if current else None

    async def _gather(self, topic: str, today: date | None, day: str) -> None:
        spec = TOPICS[topic]
        when = today or date.today()
        prompt = spec.prompt.format(date=f"{when:%A} {when.day} {when:%B %Y}")
        try:
            text = without_links(await self._ai.text(NEWS_INSTRUCTIONS, prompt, web_search=True))
        except AIError as error:
            log.warning("Couldn't look up %s: %s", topic, error)
            text = None
        # Stale finds beat none while the next lot is gathered, if they're for the same day.
        kept = self._found.get(topic)
        if text or kept is None or kept[2] != day:
            self._found[topic] = (self._clock(), text, day)
        else:
            self._found[topic] = (self._clock() - spec.seconds + FAILED_SECONDS, kept[1], day)

    async def ready(self, topics: list[str], today: date, timeout: float) -> None:
        """Waits up to `timeout` seconds for what's being gathered on `topics`, starting on any
        that aren't in yet."""
        for topic in topics:
            self.gathered(topic, today)
        running = [task for t in topics if (task := self._gathering.get(t)) and not task.done()]
        if running:
            await asyncio.wait(running, timeout=timeout)

    async def settle(self) -> None:
        """Wait for everything being gathered. For tests."""
        await asyncio.gather(*self._gathering.values())

    async def context(self, location: str, now: datetime) -> str:
        """The time, the weather and the news, for a prompt."""
        weather, news = await self.weather(location), self.news()
        lines = [clock_line(now)]
        if weather:
            lines.append(f"The weather in {location} right now: {weather}.")
        if news:
            lines.append(f"Recent music news:\n{news.strip()}")
        return "\n".join(lines)
