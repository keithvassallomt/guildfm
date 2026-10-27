"""Line-ups: the list, Now Playing's Line-ups band, and the editor."""

from tools.screenshots.camera import Frame, Scene, shot
from tools.screenshots.shots.common import CURATORS, open_now


async def open_lineup(s: Scene, name: str) -> None:
    await s.open(f"/lineups/{s.office.lineups[name]}", s.page.get_by_text("Deep Focus").first)
    await s.settle()


@shot("lineups", CURATORS)
async def lineups(s: Scene) -> Frame:
    page = s.page
    await s.open("/lineups", page.get_by_role("heading", name="Office Day"))
    await s.settle()
    return None


@shot("now-lineups", ("user", "curator"), phase="lineup")
async def now_lineups(s: Scene) -> Frame:
    page = s.page
    await open_now(s)
    if s.phone:
        sources = page.get_by_role("region", name="Sources")
        await sources.get_by_role("radio", name="Line-ups").click()
        await page.get_by_text("On now").first.wait_for()
        await s.settle()
        return sources
    band = page.locator("section").filter(has=page.locator("#band-lineups"))
    await page.get_by_text("On now").first.wait_for()
    await s.settle()
    return band.last


@shot("lineup-editor", ("curator",))
async def lineup_editor(s: Scene) -> Frame:
    await open_lineup(s, "Office Day")
    return None


@shot("lineup-slot", ("curator",))
async def lineup_slot(s: Scene) -> Frame:
    page = s.page
    await open_lineup(s, "Office Day")
    if s.phone:
        slot = page.get_by_role("button").filter(has_text="Deep Focus").filter(has_text="13:00")
    else:
        slot = page.get_by_role("button", name="Deep Focus, 13:00 to 15:30")
    await slot.click()
    await page.wait_for_timeout(300)
    if s.phone:
        return None
    await s.ring(slot)
    return [slot, page.get_by_role("region", name="Deep Focus")]
