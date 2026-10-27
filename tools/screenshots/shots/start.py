"""Getting started: signing in, a first password, Profile and installing the app."""

from tools.screenshots.camera import Frame, Scene, shot
from tools.screenshots.cast import DEMO
from tools.screenshots.shots.common import GUESTS


@shot("welcome-sign-in", GUESTS)
async def welcome_sign_in(s: Scene) -> Frame:
    page = s.page
    await s.open("/", page.get_by_role("button", name="Sign in", exact=True))
    await s.ring(page.get_by_role("radio", name="Create account"))
    return None


@shot("welcome-create", GUESTS)
async def welcome_create(s: Scene) -> Frame:
    page = s.page
    await s.open("/", page.get_by_role("radio", name="Create account"))
    await page.get_by_role("radio", name="Create account").click()
    await page.get_by_label("Display name").fill("Jo Bell")
    await page.get_by_label("Username").fill("jo")
    await page.get_by_label("Password").fill("a-good-password")
    await s.ring(page.get_by_role("button", name="Create account", exact=True))
    return None


@shot("choose-password", GUESTS, person="sam")
async def choose_password(s: Scene) -> Frame:
    page = s.page
    await s.open("/", page.get_by_role("heading", name="Choose a new password"))
    return None


@shot("profile")
async def profile(s: Scene) -> Frame:
    page = s.page
    await s.open("/profile", page.get_by_role("heading", name="Your requests"))
    await s.settle()
    return None


@shot("profile-photo", ("user",))
async def profile_photo(s: Scene) -> Frame:
    page = s.page
    await s.open("/profile", page.get_by_role("heading", name="Your requests"))
    await page.locator('input[type="file"]').set_input_files(str(DEMO / "people" / "priya.webp"))
    await page.get_by_role("button", name="Use this photo").wait_for()
    await s.settle()
    return s.sheet()


@shot("profile-on-air", ("user",))
async def profile_on_air(s: Scene) -> Frame:
    page = s.page
    await s.open("/profile", page.get_by_role("heading", name="On air"))
    await s.ring(page.get_by_role("switch"))
    return page.get_by_role("region", name="On air")


@shot("profile-install", ("user",))
async def profile_install(s: Scene) -> Frame:
    page = s.page
    await s.open("/profile", page.get_by_role("heading", name="GuildFM as an app"))
    return page.get_by_role("region", name="GuildFM as an app")


@shot("profile-help", ("user",))
async def profile_help(s: Scene) -> Frame:
    page = s.page
    await s.open("/profile", page.get_by_role("heading", name="Help"))
    await s.ring(page.get_by_role("link", name="Open the help"))
    return page.get_by_role("region", name="Help")
