"""What the shots share: who they're for, and opening the busiest pages once they're filled in."""

import re

from tools.screenshots.camera import Scene

EVERYONE = ("user", "curator", "admin")
CURATORS = ("curator", "admin")  # whoever can choose the music and make playlists and stations
ADMINS = ("admin",)
GUESTS = ("guest",)


async def open_queue(s: Scene) -> None:
    """The Queue, once the requests, the playlist's next songs and the activity are in."""
    page = s.page
    await s.open("/queue", page.get_by_role("heading", name=re.compile(r"^Then from")))
    await page.get_by_text("Mr. Blue Sky").first.wait_for()
    await page.get_by_text(re.compile(r"min ago$")).first.wait_for()
    await s.settle()


async def open_now(s: Scene) -> None:
    """Now Playing, once the song, the sources and today's plays are in."""
    page = s.page
    await s.open("/", page.get_by_role("heading", name="Played today"))
    await page.get_by_text("Mr. Blue Sky").first.wait_for()
    await page.get_by_text("Electric Feel").first.wait_for()
    await s.settle()


async def open_station(s: Scene, name: str) -> None:
    """A station's editor, once it and its cover are in."""
    page = s.page
    await s.open(f"/radio/{s.office.stations[name]}", page.get_by_label("What should it play?"))
    await page.get_by_role("button", name="Paint another").wait_for()
    await s.settle()
