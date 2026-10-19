"""Covers: OpenAI paints a square image for each AI station and each line-up from its name and
description, with the name on it, to stand in for album art.

One gets a cover when it's made, and a new one when its name or description changes, or when a
curator asks for another. Asking from an editor paints from the name and description there,
saved or not, and saving those afterwards doesn't paint another. Those without one, such as AI
picks, get theirs at startup. The images live in the media folder, like photos. If OpenAI can't
paint one, it keeps the cover it had, or its icon.
"""

import asyncio
import hashlib
import json
import logging
import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from sqlalchemy import select

from guildfm.ai import AIClient, AIError
from guildfm.models import COVERS, Lineup, Station

log = logging.getLogger(__name__)

Kind = Literal["station", "lineup"]
MODELS: dict[str, type[Station] | type[Lineup]] = {"station": Station, "lineup": Lineup}


def prompt(name: str, description: str, kind: Kind = "station") -> str:
    what = (
        "a radio station playing over the speakers in an office. What it plays"
        if kind == "station"
        else "a line-up for an office's radio: the day's shows and playlists, planned like a "
        "radio station's schedule. What it's like"
    )
    return (
        f'Square cover art for "{name}", {what}: {description}\n\n'
        "Make it look like album art: one bold, simple idea that still reads as a small "
        "thumbnail, in rich colour, filling the whole square. "
        f'Put the name, "{name}", on it as the only words, spelled exactly like that, '
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
        # Painting in the background, by kind and id.
        self._tasks: dict[tuple[str, int], asyncio.Task] = {}
        # Run after something gets a new cover, so browsers show it.
        self.on_painted: list[Callable[[], Awaitable[None]]] = []

    async def close(self) -> None:
        """Stop painting, before the database closes."""
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def settle(self) -> None:
        """Wait for covers being painted in the background. For tests."""
        await asyncio.gather(*self._tasks.values())

    def forget(self, owner: Station | Lineup) -> None:
        """Delete a station's or line-up's cover file. Its row goes separately."""
        if owner.art:
            (self._folder / owner.art).unlink(missing_ok=True)

    def paint_later(self, owner_id: int, kind: Kind = "station") -> None:
        """Paint a new cover in the background, unless that's happening already; it notices a
        change of name or description and paints again."""
        task = self._tasks.get((kind, owner_id))
        if task is None or task.done():
            self._tasks[kind, owner_id] = asyncio.create_task(self._quietly(owner_id, kind))

    async def fill_in(self) -> None:
        """Paint covers for the stations and line-ups that have none, one at a time. At
        startup."""
        for kind, model in MODELS.items():
            async with self._sessions() as db:
                waiting = list(await db.scalars(select(model.id).where(model.art.is_(None))))
            for owner_id in waiting:
                await self._quietly(owner_id, kind)

    async def _quietly(self, owner_id: int, kind: Kind) -> None:
        try:
            await self.paint(owner_id, kind=kind)
        except AIError as error:
            log.warning("Couldn't paint a cover for %s %s: %s", kind, owner_id, error)
        except Exception:
            log.exception("Painting a cover failed")

    async def paint(
        self, owner_id: int, asked: tuple[str, str] | None = None, kind: Kind = "station"
    ) -> bool:
        """Paint a new cover and wait for it: half a minute or so. From `asked`, a name and
        description, such as the editor's unsaved ones, or else the saved ones. False if it has
        gone. Raises AIError when OpenAI can't paint it."""
        model = MODELS[kind]
        while True:
            async with self._sessions() as db:
                owner = await db.get(model, owner_id)
                if owner is None:
                    return False
                wanted = asked or (owner.name, owner.description)
            data = await self._ai.image(prompt(*wanted, kind))
            self._folder.mkdir(parents=True, exist_ok=True)
            file = f"{secrets.token_urlsafe(12)}.webp"
            (self._folder / file).write_bytes(data)

            async with self._sessions() as db:
                owner = await db.get(model, owner_id)
                if owner is None:
                    (self._folder / file).unlink(missing_ok=True)
                    return False
                old, owner.art = owner.art, file
                owner.art_for = painted_from(*wanted)
                await db.commit()
                now = (owner.name, owner.description)
            if old:
                (self._folder / old).unlink(missing_ok=True)
            for callback in self.on_painted:
                await callback()
            if asked or now == wanted:
                return True
            # Renamed or redescribed while it was painting: paint it again.
