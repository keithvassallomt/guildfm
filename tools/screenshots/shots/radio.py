"""Radio: the stations, making one in the wizard, a station's page and its Change dialogs, DJs,
talk shows and jingles, the jingle generator and the hour preview."""

import re

from playwright.async_api import Locator

from tools.screenshots.camera import Frame, Scene, shot
from tools.screenshots.shots.common import CURATORS, open_station


@shot("radio", CURATORS)
async def radio(s: Scene) -> Frame:
    page = s.page
    await s.open("/radio", page.get_by_text("Xennials' Delight").first)
    await s.settle()
    return None


async def new_station(s: Scene, kind: str) -> None:
    """The wizard, with `kind` picked."""
    page = s.page
    await s.open("/radio/new", page.get_by_role("heading", name="What kind of station?"))
    await page.get_by_role("radio", name=re.compile(f"^{kind}")).click()
    await s.settle()


async def next_step(s: Scene) -> None:
    await s.page.get_by_role("button", name=re.compile(r"^Next")).click()
    await s.settle()


async def to_djs(s: Scene) -> None:
    """The wizard's DJ step for a station with a DJ, its name and music filled in."""
    page = s.page
    await new_station(s, "Music with a DJ")
    await next_step(s)
    await page.get_by_label("Station name").fill("Lunchtime Grooves")
    await page.get_by_role("button", name="Lunchtime soul").click()
    await next_step(s)
    await page.get_by_role("button", name=re.compile(r"^Della")).wait_for()


@shot("wizard-type", ("curator",))
async def wizard_type(s: Scene) -> Frame:
    await new_station(s, "Music with a DJ")
    await s.ring(s.page.get_by_role("radio", name=re.compile(r"^Music with a DJ")))
    return None


@shot("wizard-music", ("curator",))
async def wizard_music(s: Scene) -> Frame:
    page = s.page
    await new_station(s, "Music with a DJ")
    await next_step(s)
    await page.get_by_label("Station name").fill("Lunchtime Grooves")
    example = page.get_by_role("button", name="Lunchtime soul")
    await example.click()
    await s.ring(example)
    return None


@shot("wizard-djs", ("curator",))
async def wizard_djs(s: Scene) -> Frame:
    page = s.page
    await to_djs(s)
    della = page.get_by_role("button", name=re.compile(r"^Della"))
    await della.click()
    await s.settle()
    await s.ring(page.get_by_role("button", name="Hear Della"))
    return None


@shot("dj-form", ("curator",))
async def dj_form(s: Scene) -> Frame:
    page = s.page
    await to_djs(s)
    await page.get_by_role("button", name="New DJ").click()
    await page.get_by_label("Name", exact=True).fill("Kev")
    await page.get_by_label("Personality").fill(
        "Laid-back Scouser who's seen every band worth seeing, twice. Short and dry between songs."
    )
    await page.get_by_role("button", name="Cedar", exact=True).click()
    await s.settle()
    await s.ring(page.get_by_role("group", name="Voice"))
    return page.get_by_role("region", name="New DJ")


@shot("wizard-review", ("curator",))
async def wizard_review(s: Scene) -> Frame:
    page = s.page
    await to_djs(s)
    await page.get_by_role("button", name=re.compile(r"^Della")).click()
    for _ in range(3):  # Talking, Extras, Review
        await next_step(s)
    create = page.get_by_role("button", name="Create station")
    await create.wait_for()
    await s.ring(create)
    return None


@shot("wizard-talk", ("curator",))
async def wizard_talk(s: Scene) -> Frame:
    page = s.page
    await new_station(s, "Talk show")
    await s.ring(page.get_by_role("status").filter(has_text="A talk show needs"))
    return None


@shot("station-page", ("curator",))
async def station_page(s: Scene) -> Frame:
    await open_station(s, "Xennials' Delight")
    await s.ring(s.page.get_by_role("button", name="Change the name and music"))
    return None


async def change(s: Scene, station: str, part: str) -> Locator:
    """A station's page with one part's Change open, once the dialog is drawn."""
    page = s.page
    await open_station(s, station)
    await page.get_by_role("button", name=part).click()
    dialog = page.locator("dialog[open]")
    await dialog.wait_for()
    await s.settle()
    return dialog


@shot("station-talking", ("curator",))
async def station_talking(s: Scene) -> Frame:
    dialog = await change(s, "Xennials' Delight", "Change how the DJ talks")
    await s.ring(dialog.get_by_role("button", name=re.compile(r"^Every few songs")))
    return s.sheet()


@shot("station-cover", ("curator",))
async def station_cover(s: Scene) -> Frame:
    page = s.page
    await open_station(s, "Xennials' Delight")
    paint = page.get_by_role("button", name="Paint another")
    await s.ring(paint)
    return page.get_by_role("region", name="Cover")


@shot("station-jingles", ("curator",))
async def station_jingles(s: Scene) -> Frame:
    page = s.page
    await open_station(s, "Xennials' Delight")
    await s.ring(page.get_by_role("button", name="Generate jingles"))
    return page.get_by_role("region", name="Its own jingles")


@shot("talk-turn-into", ("curator",))
async def talk_turn_into(s: Scene) -> Frame:
    dialog = await change(s, "Xennials' Delight", "Change the type")
    await dialog.get_by_role("radio", name=re.compile(r"^Talk show")).click()
    await s.settle()
    await s.ring(dialog.get_by_role("button", name="Next: Hosts"))
    return s.sheet()


@shot("dj-hooks", ("curator",))
async def dj_hooks(s: Scene) -> Frame:
    dialog = await change(s, "The Lunch Break", "Change the hosts")
    await dialog.get_by_role("button", name="Change Guildbert").click()
    hooks = dialog.get_by_text("Something to talk about").locator("../..")
    await hooks.wait_for()
    await s.ring(hooks)
    return hooks


@shot("talk-mix", ("curator",))
async def talk_mix(s: Scene) -> Frame:
    dialog = await change(s, "The Lunch Break", "Change the show")
    slider = dialog.get_by_role("slider", name="How much talk?")
    await s.ring(slider)
    return slider.locator("..")


@shot("talk-prompt", ("curator",))
async def talk_prompt(s: Scene) -> Frame:
    dialog = await change(s, "The Lunch Break", "Change the show")
    await s.ring(dialog.get_by_role("button", name="Birthdays and celebs"))
    return [
        dialog.get_by_label("What's it about?"),
        dialog.get_by_text("A guide, not a script."),
    ]


@shot("talk-get-on", ("curator",))
async def talk_get_on(s: Scene) -> Frame:
    dialog = await change(s, "The Lunch Break", "Change the show")
    suggest = dialog.get_by_role("button", name="Suggest another")
    await s.ring(suggest)
    return [
        dialog.get_by_label("How do Guildbert and Debbie get on?"),
        dialog.get_by_text("Hear them together plays half a minute"),
    ]


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
