"""Playlists: the list, a playlist, adding songs, importing, and Best Voted."""

from tools.screenshots.camera import Frame, Scene, shot
from tools.screenshots.shots.common import CURATORS


async def open_playlists(s: Scene) -> None:
    await s.open("/playlists", s.page.get_by_text("Lunchtime Singalongs"))
    await s.settle()


async def open_playlist(s: Scene, name: str) -> None:
    await s.open(f"/playlists/{s.office.playlists[name]}", s.page.get_by_role("list"))
    await s.settle()


@shot("playlists", CURATORS)
async def playlists(s: Scene) -> Frame:
    await open_playlists(s)
    return None


@shot("playlist", ("curator",))
async def playlist(s: Scene) -> Frame:
    page = s.page
    await open_playlist(s, "Lunchtime Singalongs")
    await s.ring(page.get_by_role("button", name="Add songs"))
    return None


@shot("playlist-add", ("curator",))
async def playlist_add(s: Scene) -> Frame:
    page = s.page
    await open_playlist(s, "Lunchtime Singalongs")
    await page.get_by_role("button", name="Add songs").click()
    await page.get_by_role("searchbox").fill("fleetwood mac")
    await page.get_by_text("Results from Spotify.").wait_for()
    await s.settle()
    await s.ring(page.get_by_role("heading", name="Albums").locator(".."))
    return s.sheet()


@shot("playlists-import", ("curator",))
async def playlists_import(s: Scene) -> Frame:
    page = s.page
    await open_playlists(s)
    await page.get_by_role("button", name="Import from Spotify").click()
    await page.get_by_label("Spotify playlist or album link").fill(
        "https://open.spotify.com/playlist/5Rrf7mqN8uus2AaQQQNdc1"
    )
    await s.ring(page.get_by_role("button", name="Import", exact=True))
    return s.sheet()


@shot("best-voted", ("curator",))
async def best_voted(s: Scene) -> Frame:
    await open_playlist(s, "Best Voted")
    return None
