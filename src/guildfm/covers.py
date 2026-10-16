"""Stations' covers: OpenAI paints a square image for each AI station from its name and
description, with the name on it, to stand in for album art.

A station gets one when it's made, and a new one when its name or description changes, or when
a curator asks for another. Asking from the editor paints from the name and description there,
saved or not, and saving those afterwards doesn't paint another. Stations without one, such as
AI picks, get theirs at startup. The images live in the media folder, like photos. If OpenAI
can't paint one, the station keeps the cover it had, or the radio icon.
"""

import asyncio
import hashlib
import json
import logging
import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path

from sqlalchemy import select

from guildfm.ai import AIClient, AIError
from guildfm.models import COVERS, Station

log = logging.getLogger(__name__)


def prompt(name: str, description: str) -> str:
    return (
        f'Square cover art for "{name}", a radio station playing over the speakers in an '
        f"office. What it plays: {description}\n\n"
        "Make it look like album art: one bold, simple idea that still reads as a small "
        "thumbnail, in rich colour, filling the whole square. "
        f'Put the station\'s name, "{name}", on it as the only words, spelled exactly like that, '
        "in a bold, clear typeface that's easy to read when the cover is small. No other text, "
        "numbers or logos."
    )


def painted_from(name: str, description: str) -> str:
    """A cover's name and description, short, to tell whether they've changed since."""
    return hashlib.sha256(json.dumps([name, description]).encode()).hexdigest()[:32]


class Painter:
    def __init__(self, sessionmaker, ai: AIClient, media_dir: Path) -> None:
        self._sessions = sessionmaker
        self._ai = ai
        self._folder = media_dir / COVERS
        self._tasks: dict[int, asyncio.Task] = {}  # station id: painting in the background
        # Run after a station gets a new cover, so browsers show it.
        self.on_painted: list[Callable[[], Awaitable[None]]] = []

    async def close(self) -> None:
        """Stop painting, before the database closes."""
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def settle(self) -> None:
        """Wait for covers being painted in the background. For tests."""
        await asyncio.gather(*self._tasks.values())

    def forget(self, station: Station) -> None:
        """Delete the station's cover file. Its row goes separately."""
        if station.art:
            (self._folder / station.art).unlink(missing_ok=True)

    def paint_later(self, station_id: int) -> None:
        """Paint the station a new cover in the background, unless that's happening already;
        it notices a change of name or description and paints again."""
        task = self._tasks.get(station_id)
        if task is None or task.done():
            self._tasks[station_id] = asyncio.create_task(self._quietly(station_id))

    async def fill_in(self) -> None:
        """Paint covers for the stations that have none, one at a time. At startup."""
        async with self._sessions() as db:
            waiting = list(await db.scalars(select(Station.id).where(Station.art.is_(None))))
        for station_id in waiting:
            await self._quietly(station_id)

    async def _quietly(self, station_id: int) -> None:
        try:
            await self.paint(station_id)
        except AIError as error:
            log.warning("Couldn't paint a cover for station %s: %s", station_id, error)
        except Exception:
            log.exception("Painting a station's cover failed")

    async def paint(self, station_id: int, asked: tuple[str, str] | None = None) -> bool:
        """Paint the station a new cover and wait for it: half a minute or so. From `asked`, a
        name and description, such as the editor's unsaved ones, or else the saved ones. False
        if the station has gone. Raises AIError when OpenAI can't paint it."""
        while True:
            async with self._sessions() as db:
                station = await db.get(Station, station_id)
                if station is None:
                    return False
                wanted = asked or (station.name, station.description)
            data = await self._ai.image(prompt(*wanted))
            self._folder.mkdir(parents=True, exist_ok=True)
            file = f"{secrets.token_urlsafe(12)}.webp"
            (self._folder / file).write_bytes(data)

            async with self._sessions() as db:
                station = await db.get(Station, station_id)
                if station is None:
                    (self._folder / file).unlink(missing_ok=True)
                    return False
                old, station.art = station.art, file
                station.art_for = painted_from(*wanted)
                await db.commit()
                now = (station.name, station.description)
            if old:
                (self._folder / old).unlink(missing_ok=True)
            for callback in self.on_painted:
                await callback()
            if asked or now == wanted:
                return True
            # Renamed or redescribed while it was painting: paint it again.
