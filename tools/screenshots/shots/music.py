"""Choosing the music: the playback controls, the room volumes, the quick controls and the
sources on Now Playing."""

from tools.screenshots.camera import Frame, Scene, shot
from tools.screenshots.shots.common import ADMINS, CURATORS, open_now, open_queue


@shot("now-controls", CURATORS)
async def now_controls(s: Scene) -> Frame:
    page = s.page
    await open_now(s)
    await s.ring(page.get_by_role("button", name="Pause").locator(".."))
    return page.get_by_role("region", name="Now playing")


@shot("now-rooms", ADMINS)
async def now_rooms(s: Scene) -> Frame:
    page = s.page
    await open_now(s)
    await page.get_by_role("button", name="Rooms").click()
    await page.get_by_text("Donut Shop").wait_for()
    await s.ring(page.get_by_role("button", name="Stop all"))
    return page.get_by_role("region", name="Now playing")


@shot("quick-controls", ADMINS)
async def quick_controls(s: Scene) -> Frame:
    page = s.page
    await open_queue(s)
    await page.get_by_role("button", name="Quick controls").click()
    await page.get_by_role("dialog").get_by_role("button", name="Pause").wait_for()
    await s.settle()
    return None


@shot("now-sources", CURATORS)
async def now_sources(s: Scene) -> Frame:
    page = s.page
    await open_now(s)
    if s.phone:
        sources = page.get_by_role("region", name="Sources")
        await sources.get_by_role("radio", name="Playlists").click()
        await page.wait_for_timeout(300)
        await s.ring(sources.get_by_role("button").filter(has_text="Lunchtime Singalongs"))
        return sources
    bands = page.get_by_role("region", name="Queue").locator("..")
    await s.ring(page.get_by_role("button").filter(has_text="Lunchtime Singalongs"))
    return bands


@shot("now-requests-only", CURATORS)
async def now_requests_only(s: Scene) -> Frame:
    page = s.page
    await open_now(s)
    only = page.get_by_role("button", name="Requests only")
    await s.ring(only)
    if s.phone:
        return page.get_by_role("region", name="Sources")
    return page.get_by_role("region", name="Queue")
