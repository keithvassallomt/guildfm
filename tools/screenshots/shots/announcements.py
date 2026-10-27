"""Announcements: the page, the editor, and the quick one on Now Playing."""

import re

from tools.screenshots.camera import Frame, Scene, shot
from tools.screenshots.shots.common import ADMINS, open_now


@shot("announcements", ADMINS)
async def announcements(s: Scene) -> Frame:
    page = s.page
    await s.open("/admin/announcements", page.get_by_role("heading", name="Scheduled"))
    await s.ring(page.get_by_role("link", name="New", exact=True))
    return None


async def new_announcement(s: Scene) -> None:
    page = s.page
    await s.open("/admin/announcements/new", page.get_by_label("What should it say?"))
    await page.get_by_label("What should it say?").fill(
        "The pizza's here! [excited] Come to the kitchen while it's hot."
    )
    await page.get_by_role("button", name="Kitchen").click()
    await page.get_by_role("button", name="Upstairs Lounge").click()


@shot("announcement-message", ADMINS)
async def announcement_message(s: Scene) -> Frame:
    await new_announcement(s)
    page = s.page
    await s.ring(page.get_by_role("button", name=re.compile(r"Preview")))
    return page.locator("form > div").first


@shot("announcement-when", ADMINS)
async def announcement_when(s: Scene) -> Frame:
    await new_announcement(s)
    page = s.page
    await page.get_by_role("radio", name="Schedule").click()
    await page.get_by_label("Starting").fill("2026-10-16")
    await page.get_by_label("At", exact=True).fill("12:45")
    await page.get_by_role("radio", name="Chosen days").click()
    await page.get_by_role("button", name="Friday").click()
    await s.settle()
    await s.ring(page.get_by_text(re.compile(r"^Plays in ")))
    return page.locator("form > div").nth(1)


@shot("announcement-card", ADMINS)
async def announcement_card(s: Scene) -> Frame:
    page = s.page
    await s.open("/admin/announcements", page.get_by_role("heading", name="Scheduled"))
    card = page.locator("li").filter(has_text="Lunch is ready").filter(has_text="Play now")
    await s.ring(card.get_by_role("button", name="Play now").locator(".."))
    return card


@shot("quick-announcement", ADMINS)
async def quick_announcement(s: Scene) -> Frame:
    page = s.page
    await open_now(s)
    await page.get_by_role("button", name="Announce").click()
    await page.get_by_label("What should it say?").fill(
        "Fire drill in five minutes, everyone. Please head to the car park when the alarm goes."
    )
    await s.ring(page.get_by_role("radio", name="After this song").locator(".."))
    return s.sheet()
