"""Listening and requesting: Now Playing, the Queue, and when the music stops."""

import re

from tools.screenshots.camera import Frame, Scene, shot
from tools.screenshots.shots.common import EVERYONE, open_now, open_queue

# Each reader's own request, in the queue the office is seeded with.
OWN_REQUEST = {
    "user": "Dreams - 2004 Remaster",
    "curator": "Don't Stop Me Now",
    "admin": "Levitating",
}


# Now Playing


@shot("now-playing")
async def now_playing(s: Scene) -> Frame:
    await open_now(s)
    return None


@shot("now-history", ("user",))
async def now_history(s: Scene) -> Frame:
    await open_now(s)
    page = s.page
    history = page.get_by_role("region", name="Played today")
    return [history.get_by_role("heading"), history.locator("li").nth(4)]


@shot("now-takeover", EVERYONE, phase="takeover")
async def now_takeover(s: Scene) -> Frame:
    page = s.page
    await s.open("/", page.get_by_text("Someone's playing something from the Sonos app"))
    await s.settle()
    await s.ring(page.get_by_role("status").filter(has_text="Sonos app"))
    return None


# The Queue


@shot("queue")
async def queue(s: Scene) -> Frame:
    await open_queue(s)
    return None


@shot("queue-search")
async def queue_search(s: Scene) -> Frame:
    page = s.page
    await open_queue(s)
    await page.get_by_role("button", name="Search for a song to request").click()
    await page.get_by_role("searchbox").fill("fleetwood mac")
    await page.get_by_text("Results from Spotify.").wait_for()
    await s.settle()
    await s.ring(page.get_by_role("button", name=re.compile(r"^Add ")).first)
    return s.sheet()


@shot("queue-vote")
async def queue_vote(s: Scene) -> Frame:
    page = s.page
    await open_queue(s)
    thumbs = page.get_by_role("button", name="Thumbs up for golden hour")
    await s.ring(thumbs.locator(".."))
    return page.locator("li").filter(has=thumbs)


@shot("queue-up-next")
async def queue_up_next(s: Scene) -> Frame:
    page = s.page
    await open_queue(s)
    await s.ring(page.get_by_text("Locked in, already sent to the speakers"))
    return page.get_by_role("region", name="Up next")


@shot("queue-upcoming")
async def queue_upcoming(s: Scene) -> Frame:
    page = s.page
    heading = page.get_by_role("heading", name=re.compile(r"^Then from"))
    await open_queue(s)
    await s.ring(page.get_by_role("button", name=re.compile(r"^Thumbs down for")).nth(-2))
    return heading.locator("..")


@shot("queue-remove")
async def queue_remove(s: Scene) -> Frame:
    page = s.page
    title = OWN_REQUEST[s.role]
    await open_queue(s)
    await page.get_by_role("button", name=f"Show actions for {title}").click()
    await page.wait_for_timeout(300)
    await s.ring(page.get_by_role("button", name=f"Remove {title}"))
    return page.locator("li").filter(has=page.get_by_role("button", name=f"Remove {title}"))
