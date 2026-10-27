"""Gathers the demo office's real pieces, once: the songs, artists and albums in cast.py from
Spotify with their artwork, photos of the invented people, and covers for the stations and
line-ups, painted by OpenAI as GuildFM would paint them. Uses the keys in .env. Anything already
gathered is left alone, so running it again only fetches what's new.

    uv run python -m tools.screenshots.fetch"""

import asyncio
import io
import json
from typing import Any

import httpx2
from PIL import Image

from guildfm.ai import AIClient
from guildfm.config import get_settings
from guildfm.covers import prompt as cover_prompt
from guildfm.spotify import API, SpotifyClient
from tools.screenshots.cast import ALBUMS, ARTISTS, COVERS, DEMO, PEOPLE, SONGS, slug

CATALOGUE = DEMO / "catalogue.json"
ART = DEMO / "art"
PHOTOS = DEMO / "people"
PAINTED = DEMO / "covers"
ART_SIZE = 400  # sharp enough for the largest cover on Now Playing at twice the pixels
PHOTO_SIZE = 256  # what GuildFM crops profile photos to
COVER_SIZE = 512  # sharp in the station editor, the largest place a cover shows

PHOTO_PROMPT = (
    "A natural, friendly head-and-shoulders photograph of {looks}, looking at the camera. Soft "
    "daylight in a bright modern office, the background softly blurred. Realistic, like a "
    "colleague's profile photo. No text."
)


def square(data: bytes, size: int) -> Image.Image:
    """A picture cropped to a square from its middle and shrunk to `size`."""
    picture = Image.open(io.BytesIO(data)).convert("RGB")
    side = min(picture.size)
    left, top = (picture.width - side) // 2, (picture.height - side) // 2
    return picture.crop((left, top, left + side, top + side)).resize(
        (size, size), Image.Resampling.LANCZOS
    )


class Spotify:
    def __init__(self, token: str) -> None:
        self._http = httpx2.AsyncClient(
            base_url=API, headers={"Authorization": f"Bearer {token}"}, timeout=30
        )

    async def get(self, path: str, **params: Any) -> dict[str, Any]:
        response = await self._http.get(path, params={"market": "GB", **params})
        response.raise_for_status()
        return response.json()

    async def art(self, item_id: str, images: list[dict[str, Any]]) -> None:
        if (ART / f"{item_id}.jpg").exists() or not images:
            return
        response = await self._http.get(images[0]["url"])  # the largest, usually 640 px
        response.raise_for_status()
        square(response.content, ART_SIZE).save(ART / f"{item_id}.jpg", quality=85)

    async def close(self) -> None:
        await self._http.aclose()


def song(item: dict[str, Any], album: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "name": item["name"],
        "artists": [artist["name"] for artist in item["artists"]],
        "album": {"id": album["id"], "name": album["name"]},
        "duration_ms": item["duration_ms"],
        "explicit": item["explicit"],
    }


async def find_song(spotify: Spotify, title: str, artist: str) -> dict[str, Any]:
    found = await spotify.get(
        "/search", q=f'track:"{title}" artist:"{artist}"', type="track", limit=10
    )
    for item in found["tracks"]["items"]:
        names = " ".join(a["name"] for a in item["artists"]).lower()
        if item.get("is_playable", True) and not item["explicit"] and artist.lower() in names:
            await spotify.art(item["album"]["id"], item["album"]["images"])
            return {"wanted": [title, artist]} | song(item, item["album"])
    raise LookupError(f"Spotify has no clean, playable {title} by {artist}")


async def find_artist(spotify: Spotify, name: str) -> dict[str, Any]:
    found = await spotify.get("/search", q=name, type="artist", limit=1)
    item = found["artists"]["items"][0]
    await spotify.art(item["id"], item["images"])
    return {"wanted": name, "id": item["id"], "name": item["name"]}


async def find_album(spotify: Spotify, name: str, artist: str) -> dict[str, Any]:
    found = await spotify.get(
        "/search", q=f'album:"{name}" artist:"{artist}"', type="album", limit=5
    )
    item = next(a for a in found["albums"]["items"] if a["album_type"] == "album")
    album = await spotify.get(f"/albums/{item['id']}")
    await spotify.art(album["id"], album["images"])
    songs = [
        song(track, album)
        for track in album["tracks"]["items"]
        if track.get("is_playable", True) and not track["explicit"]
    ]
    return {
        "wanted": [name, artist],
        "id": album["id"],
        "name": album["name"],
        "artists": [a["name"] for a in album["artists"]],
        "release_date": album["release_date"],
        "album_type": album["album_type"],
        "songs": songs,
    }


async def gather_music() -> None:
    catalogue = (
        json.loads(CATALOGUE.read_text())
        if CATALOGUE.exists()
        else {"songs": [], "artists": [], "albums": []}
    )
    have = {
        "songs": {tuple(s["wanted"]) for s in catalogue["songs"]},
        "artists": {a["wanted"] for a in catalogue["artists"]},
        "albums": {tuple(a["wanted"]) for a in catalogue["albums"]},
    }
    settings = get_settings()
    client = SpotifyClient(
        client_id=settings.spotify_client_id,
        client_secret=settings.spotify_client_secret.get_secret_value(),
        redirect_uri=settings.spotify_redirect_uri,
        market="GB",
    )
    spotify = Spotify(await client.app_token())

    def save() -> None:
        CATALOGUE.write_text(json.dumps(catalogue, indent=1, ensure_ascii=False) + "\n")

    try:
        for title, artist in SONGS:
            if (title, artist) not in have["songs"]:
                catalogue["songs"].append(await find_song(spotify, title, artist))
                save()
                print(f"Found {title} by {artist}")
        for name in ARTISTS:
            if name not in have["artists"]:
                catalogue["artists"].append(await find_artist(spotify, name))
                save()
                print(f"Found the artist {name}")
        for name, artist in ALBUMS:
            if (name, artist) not in have["albums"]:
                catalogue["albums"].append(await find_album(spotify, name, artist))
                save()
                print(f"Found the album {name} by {artist}")
    finally:
        await spotify.close()
        await client.close()


def painter() -> AIClient:
    settings = get_settings()
    return AIClient(
        settings.openai_api_key.get_secret_value(),
        settings.openai_model,
        image_model=settings.openai_image_model,
        image_quality=settings.openai_image_quality,
    )


async def paint_people() -> None:
    ai = painter()
    try:
        wanted = [p for p in PEOPLE if p.looks and not (PHOTOS / f"{p.username}.webp").exists()]
        photos = await asyncio.gather(
            *(ai.image(PHOTO_PROMPT.format(looks=person.looks)) for person in wanted)
        )
        for person, photo in zip(wanted, photos, strict=True):
            square(photo, PHOTO_SIZE).save(PHOTOS / f"{person.username}.webp", quality=85)
            print(f"Painted {person.name}")
    finally:
        await ai.close()


async def paint_covers() -> None:
    """Covers from GuildFM's own prompt, so they look like the ones it paints."""
    ai = painter()
    try:
        wanted = [c for c in COVERS if not (PAINTED / f"{slug(c[0])}.webp").exists()]
        covers = await asyncio.gather(
            *(ai.image(cover_prompt(name, about, kind)) for name, about, kind in wanted)
        )
        for (name, _, _), cover in zip(wanted, covers, strict=True):
            square(cover, COVER_SIZE).save(PAINTED / f"{slug(name)}.webp", quality=85)
            print(f"Painted a cover for {name}")
    finally:
        await ai.close()


async def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    PHOTOS.mkdir(parents=True, exist_ok=True)
    PAINTED.mkdir(parents=True, exist_ok=True)
    await asyncio.gather(gather_music(), paint_people(), paint_covers())


if __name__ == "__main__":
    asyncio.run(main())
