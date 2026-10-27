"""Radio: the stations, the station editor, its DJ and jingles, the jingle generator and the
hour preview."""

import re

from tools.screenshots.camera import Frame, Scene, shot
from tools.screenshots.shots.common import CURATORS, open_station


@shot("radio", CURATORS)
async def radio(s: Scene) -> Frame:
    page = s.page
    await s.open("/radio", page.get_by_text("Xennials' Delight").first)
    await s.settle()
    return None


@shot("station-editor", ("curator",))
async def station_editor(s: Scene) -> Frame:
    await open_station(s, "Xennials' Delight")
    return None


@shot("station-cover", ("curator",))
async def station_cover(s: Scene) -> Frame:
    page = s.page
    await open_station(s, "Xennials' Delight")
    paint = page.get_by_role("button", name="Paint another")
    await s.ring(paint)
    return paint.locator("../..")


@shot("station-switches", ("curator",))
async def station_switches(s: Scene) -> Frame:
    page = s.page
    await open_station(s, "Xennials' Delight")
    name = page.get_by_role("textbox", name="Name", exact=True)
    return [name, page.get_by_text("Crossfade between songs")]


@shot("station-dj", ("curator",))
async def station_dj(s: Scene) -> Frame:
    page = s.page
    await open_station(s, "Xennials' Delight")
    await s.ring(page.locator("fieldset").filter(has_text="Which DJ"))
    return [page.get_by_role("heading", name="DJ", exact=True), page.get_by_label("Personality")]


@shot("station-voice", ("curator",))
async def station_voice(s: Scene) -> Frame:
    page = s.page
    await open_station(s, "Xennials' Delight")
    await s.ring(page.get_by_role("button", name="Preview", exact=True))
    voice = page.get_by_role("group", name="Voice")
    return [voice, page.get_by_role("button", name="Preview", exact=True)]


@shot("station-talk", ("curator",))
async def station_talk(s: Scene) -> Frame:
    page = s.page
    await open_station(s, "Xennials' Delight")
    return [
        page.locator("fieldset").filter(has_text="How often the DJ talks"),
        page.get_by_text("The DJ talks between songs, so every room hears it in step."),
    ]


@shot("station-jingles", ("curator",))
async def station_jingles(s: Scene) -> Frame:
    page = s.page
    await open_station(s, "Xennials' Delight")
    await s.ring(page.get_by_role("button", name="Generate jingles"))
    return page.get_by_role("region", name="Jingles")


@shot("generator-describe", ("curator",))
async def generator_describe(s: Scene) -> Frame:
    page = s.page
    await open_station(s, "Friday Feeling")
    await page.get_by_role("button", name="Generate jingles").click()
    await page.get_by_role("button", name="Less (How many jingles)").click()
    await page.get_by_label("Describe jingle 1").fill(
        'Big disco strings and a funky bass line, then a choir singing "Friday Feeling!" to finish.'
    )
    await page.get_by_role("button", name="Write jingle 2 with AI").click()
    await page.get_by_text("Written by AI").wait_for()
    await s.settle()
    await s.ring(page.get_by_role("button", name=re.compile(r"^Generate 2 jingles")))
    return s.sheet()


@shot("generator-review", ("curator",), phase="drafts")
async def generator_review(s: Scene) -> Frame:
    page = s.page
    await open_station(s, "Friday Feeling")
    await page.get_by_role("button", name="Generate jingles").click()
    keep = page.get_by_role("button", name="Keep").first
    await keep.wait_for()
    await s.settle()
    await s.ring(keep.locator(".."))
    return s.sheet()


@shot("hour-preview", ("curator",))
async def hour_preview(s: Scene) -> Frame:
    page = s.page
    await open_station(s, "Xennials' Delight")
    await page.get_by_role("button", name="Preview an hour").click()
    await page.get_by_role("button", name="Try another hour").wait_for(timeout=60_000)
    await s.settle()
    return s.sheet()
