"""Running GuildFM: Admin, Users, Jingles, Settings, monitor mode and Status."""

from tools.screenshots.camera import Frame, Scene, shot
from tools.screenshots.shots.common import ADMINS


async def open_settings(s: Scene) -> None:
    await s.open("/admin/settings", s.page.get_by_role("heading", name="Playback hours"))
    await s.page.get_by_text("Connected as Office Spotify").wait_for()
    await s.settle()


@shot("admin", ADMINS)
async def admin(s: Scene) -> Frame:
    await s.open("/admin", s.page.get_by_role("link", name="Announcements").last)
    return None


@shot("users", ADMINS)
async def users(s: Scene) -> Frame:
    await s.open("/admin/users", s.page.get_by_text("Owen Hughes"))
    await s.settle()
    return None


@shot("users-manage", ADMINS)
async def users_manage(s: Scene) -> Frame:
    page = s.page
    await s.open("/admin/users", page.get_by_text("Owen Hughes"))
    manage = page.get_by_role("button", name="Manage Owen Hughes")
    # On a desktop, everyone's controls are always out.
    if await manage.is_visible():
        await manage.click()
        await page.wait_for_timeout(300)
    role = page.get_by_role("radiogroup", name="Role for Owen Hughes")
    await s.ring(role)
    return page.locator("li").filter(has=role)


@shot("users-add", ADMINS)
async def users_add(s: Scene) -> Frame:
    page = s.page
    await s.open("/admin/users", page.get_by_text("Owen Hughes"))
    await page.get_by_role("button", name="Add", exact=True).click()
    await page.get_by_label("Display name").fill("Jo Bell")
    await page.get_by_label("Username").fill("jo")
    await s.ring(page.get_by_role("button", name="Create account"))
    return s.sheet()


@shot("jingles", ADMINS)
async def jingles(s: Scene) -> Frame:
    page = s.page
    await s.open("/admin/jingles", page.get_by_text("GuildFM Jingle"))
    await s.settle()
    return None


def section(s: Scene, name: str):
    return s.page.get_by_role("region", name=name)


@shot("settings-voting", ADMINS)
async def settings_voting(s: Scene) -> Frame:
    await open_settings(s)
    return [section(s, "Queue and voting"), section(s, "Best Voted playlist")]


@shot("settings-runs-out", ADMINS)
async def settings_runs_out(s: Scene) -> Frame:
    await open_settings(s)
    return section(s, "When the queue runs out")


@shot("settings-hours", ADMINS)
async def settings_hours(s: Scene) -> Frame:
    await open_settings(s)
    return section(s, "Playback hours")


@shot("settings-voice", ADMINS)
async def settings_voice(s: Scene) -> Frame:
    await open_settings(s)
    return section(s, "AI and voice")


@shot("settings-connections", ADMINS)
async def settings_connections(s: Scene) -> Frame:
    await open_settings(s)
    return [section(s, "Connections"), section(s, "Sonos")]


@shot("settings-monitor", ADMINS)
async def settings_monitor(s: Scene) -> Frame:
    await open_settings(s)
    await s.ring(section(s, "Monitor mode").get_by_role("switch"))
    return section(s, "Monitor mode")


@shot("monitor-bar", ADMINS, phase="monitor")
async def monitor_bar(s: Scene) -> Frame:
    page = s.page
    await s.open("/queue", page.get_by_role("button", name="Listen here"))
    await s.settle()
    await s.ring(page.get_by_role("button", name="Listen here"))
    return None


@shot("status", ADMINS)
async def status(s: Scene) -> Frame:
    page = s.page
    await s.open("/admin/status", page.get_by_role("heading", name="Backups"))
    await s.settle()
    return None
