"""Spotify's Web API: searching the catalogue, and the account connected for playlist import.

Searching uses GuildFM's own app token. Playlist import needs a person's Spotify account,
connected once through Spotify's sign-in page and kept fresh with its refresh token.
"""

import contextlib
import logging
import math
import secrets
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx2
from sqlalchemy import func
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.health import Health
from guildfm.models import SpotifyAccount, Track

log = logging.getLogger(__name__)

API = "https://api.spotify.com/v1"
ACCOUNTS = "https://accounts.spotify.com"
SCOPES = "playlist-read-private playlist-read-collaborative"
PAGE = 10  # the most results a development-mode app may ask for at once
SEARCH_KEPT_SECONDS = 10 * 60  # how long a page of search results is reused
SEARCHES_KEPT = 500  # pages of search results kept at once
WAIT_UNSAID = 30  # seconds to hold off when Spotify says it's busy without saying how long
SHORT_WAIT = 2 * 60  # a pause shorter than this is given in seconds, not as a time of day
IMPORT_PAGE = 50  # playlist items Spotify returns at once
IMPORT_LIMIT = 1000  # the most tracks GuildFM imports from one playlist
STATE_SECONDS = 10 * 60  # how long a "connect Spotify" link stays valid
# Spotify asks people to reconnect about six months after they first connected.
RECONNECT_SECONDS = 182 * 24 * 60 * 60


class SpotifyError(Exception):
    """Something went wrong with Spotify. The message is fit to show people."""


class SpotifyBusy(SpotifyError):
    """Spotify is rate limiting GuildFM, until `until` (seconds since the epoch)."""

    def __init__(self, message: str, until: float) -> None:
        super().__init__(message)
        self.until = until


class SpotifyNotFound(SpotifyError):
    """Spotify doesn't have the thing asked for."""


class SpotifyForbidden(SpotifyError):
    """Spotify won't share it with GuildFM, such as a playlist the account doesn't own."""


class NotConnected(SpotifyError):
    """No Spotify account is connected, or Spotify has signed it out."""


@dataclass(frozen=True)
class SpotifyTrack:
    id: str
    title: str
    artists: str
    album: str
    duration_ms: int
    explicit: bool
    art_url: str | None


@dataclass(frozen=True)
class SpotifyArtist:
    id: str
    name: str
    art_url: str | None


@dataclass(frozen=True)
class SpotifyAlbum:
    id: str
    name: str
    artists: str
    art_url: str | None
    year: str | None
    kind: str  # "album", "single" or "compilation"
    tracks: int


@dataclass(frozen=True)
class SearchResults:
    tracks: list[SpotifyTrack]
    artists: list[SpotifyArtist]  # with the first page only
    albums: list[SpotifyAlbum]  # with the first page, when asked for
    more: bool  # there are more tracks


def _image(images: list[dict[str, Any]]) -> str | None:
    """Spotify lists artwork largest first, usually 640, 300 and 64 px. 300 suits GuildFM."""
    if not images:
        return None
    return images[1]["url"] if len(images) > 1 else images[0]["url"]


def _track(item: dict[str, Any]) -> SpotifyTrack:
    return SpotifyTrack(
        id=item["id"],
        title=item["name"],
        artists=", ".join(artist["name"] for artist in item["artists"]),
        album=item["album"]["name"],
        duration_ms=item["duration_ms"],
        explicit=item["explicit"],
        art_url=_image(item["album"].get("images") or []),
    )


def _artist(item: dict[str, Any]) -> SpotifyArtist:
    return SpotifyArtist(id=item["id"], name=item["name"], art_url=_image(item.get("images") or []))


def _album(item: dict[str, Any]) -> SpotifyAlbum:
    return SpotifyAlbum(
        id=item["id"],
        name=item["name"],
        artists=", ".join(artist["name"] for artist in item["artists"]),
        art_url=_image(item.get("images") or []),
        year=(item.get("release_date") or "")[:4] or None,
        kind=item.get("album_type") or "album",
        tracks=item.get("total_tracks") or 0,
    )


class SpotifyClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        market: str,
        http: httpx2.AsyncClient | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._id = client_id
        self._secret = client_secret
        self._redirect_uri = redirect_uri
        self._market = market
        self._http = http or httpx2.AsyncClient(timeout=10)
        self._clock = clock
        self._app_token: tuple[str, float] | None = None
        # When Spotify rate limits GuildFM it says how long to wait. Nothing is sent before
        # then, since asking again while paused can make Spotify pause GuildFM for longer.
        self.paused_until = 0.0
        self.zone = ZoneInfo("UTC")  # the office's, set by the app, for saying until when
        self._calls: deque[float] = deque()  # when each call in the last minute was made
        self._searches: dict[tuple[str, str, int], tuple[float, dict[str, Any]]] = {}
        # "Connect Spotify" links handed out, waiting for Spotify to send people back.
        self._states: dict[str, float] = {}
        self.health = Health()

    async def close(self) -> None:
        await self._http.aclose()

    # Talking to Spotify

    @property
    def paused(self) -> bool:
        return self.paused_until > self._clock()

    def not_paused(self) -> None:
        """Raises SpotifyBusy while Spotify has GuildFM paused."""
        if self.paused:
            raise self._busy()

    def _busy(self) -> SpotifyBusy:
        now = self._clock()
        seconds = math.ceil(self.paused_until - now)
        if seconds < SHORT_WAIT:
            plural = "" if seconds == 1 else "s"
            return SpotifyBusy(
                f"Spotify is busy. Try again in {seconds} second{plural}.", self.paused_until
            )
        # Rounded up to the minute, so it's over by the time it says.
        at = datetime.fromtimestamp(math.ceil(self.paused_until / 60) * 60, self.zone)
        days = (at.date() - datetime.fromtimestamp(now, self.zone).date()).days
        day = "" if days == 0 else " tomorrow" if days == 1 else f" on {at:%A}"
        message = f"Spotify has paused searching until {at:%H:%M}{day}."
        return SpotifyBusy(message, self.paused_until)

    def _calling(self) -> None:
        """Before each call: refuse while paused, and count it."""
        self.not_paused()
        now = self._clock()
        self._calls.append(now)
        while self._calls[0] < now - 60:
            self._calls.popleft()

    def _rate_limited(self, response: httpx2.Response) -> SpotifyBusy:
        """Spotify said to slow down: pause for as long as it asked."""
        try:
            wait = max(1, int(response.headers["Retry-After"]))
        except KeyError, ValueError:
            wait = WAIT_UNSAID
        self.paused_until = max(self.paused_until, self._clock() + wait)
        log.warning(
            "Spotify asked GuildFM to wait %s seconds, after %s calls in the last minute",
            wait,
            len(self._calls),
        )
        return self._busy()

    async def _token(self, form: dict[str, str]) -> dict[str, Any]:
        with self._noted():
            return await self._ask_token(form)

    async def _ask_token(self, form: dict[str, str]) -> dict[str, Any]:
        self._calling()
        try:
            response = await self._http.post(
                f"{ACCOUNTS}/api/token", data=form, auth=(self._id, self._secret)
            )
        except httpx2.HTTPError as error:
            raise SpotifyError("Couldn't reach Spotify. Check the internet connection.") from error
        if response.status_code == 429:
            raise self._rate_limited(response)
        if response.status_code == 400 and response.json().get("error") == "invalid_grant":
            raise NotConnected("Spotify signed GuildFM out of the account. Connect it again.")
        if response.status_code >= 400:
            raise SpotifyError("Spotify turned GuildFM's keys down. Check them in .env.")
        return response.json()

    async def app_token(self) -> str:
        if self._app_token and self._app_token[1] > self._clock() + 60:
            return self._app_token[0]
        data = await self._token({"grant_type": "client_credentials"})
        self._app_token = (data["access_token"], self._clock() + data["expires_in"])
        return data["access_token"]

    @contextlib.contextmanager
    def _noted(self):
        """Note how a call went, for the status page. Spotify not having something, or not
        sharing it, isn't Spotify failing."""
        try:
            yield
        except SpotifyNotFound, SpotifyForbidden:
            self.health.worked()
            raise
        except SpotifyError as error:
            self.health.failed(str(error))
            raise
        self.health.worked()

    async def _get(self, path: str, params: dict | None = None, user_token: str | None = None):
        with self._noted():
            return await self._fetch(path, params, user_token)

    async def _fetch(self, path: str, params: dict | None, user_token: str | None):
        for attempt in range(2):
            token = user_token or await self.app_token()
            self._calling()
            try:
                response = await self._http.get(
                    f"{API}{path}", params=params, headers={"Authorization": f"Bearer {token}"}
                )
            except httpx2.HTTPError as error:
                raise SpotifyError(
                    "Couldn't reach Spotify. Check the internet connection."
                ) from error
            if response.status_code == 401 and user_token is None and attempt == 0:
                self._app_token = None  # expired early; get a new one and try once more
                continue
            if response.status_code == 404 or (
                response.status_code == 400 and path.startswith(("/tracks/", "/albums/"))
            ):
                raise SpotifyNotFound("Spotify doesn't have that.")
            if response.status_code == 403:
                raise SpotifyForbidden("Spotify won't share that with GuildFM.")
            if response.status_code == 429:
                raise self._rate_limited(response)
            if response.status_code >= 400:
                raise SpotifyError("Spotify couldn't do that just now. Try again.")
            return response.json()
        raise SpotifyError("Spotify turned GuildFM's keys down. Check them in .env.")

    # The catalogue

    async def search(self, query: str, offset: int = 0, albums: bool = False) -> SearchResults:
        """A page of tracks matching `query` from `offset`: 10, Spotify's most for a
        development-mode app. Artists come with the first page, and albums too when `albums`
        is set. The same search within a few minutes is answered from memory."""
        types = ("track,artist,album" if albums else "track,artist") if offset == 0 else "track"
        result = await self._search_page(query, types, offset)
        # A page can repeat a track; each one appears once. Songs that can't play here are left
        # out, as for albums and playlists.
        found = {
            item["id"]: item
            for item in result["tracks"]["items"]
            if item and item.get("is_playable", True)
        }
        return SearchResults(
            tracks=[_track(item) for item in found.values()],
            artists=[_artist(item) for item in result.get("artists", {}).get("items", []) if item],
            albums=[_album(item) for item in result.get("albums", {}).get("items", []) if item],
            more=result["tracks"].get("next") is not None,
        )

    async def _search_page(self, query: str, types: str, offset: int) -> dict[str, Any]:
        now = self._clock()
        key = (" ".join(query.lower().split()), types, offset)
        kept = self._searches.get(key)
        if kept and kept[0] > now:
            return kept[1]
        params = {"q": query, "type": types, "limit": PAGE, "offset": offset}
        result = await self._get("/search", params | {"market": self._market})
        self._searches.pop(key, None)  # so it goes to the end, as the newest
        self._searches[key] = (now + SEARCH_KEPT_SECONDS, result)
        if len(self._searches) > SEARCHES_KEPT:
            self._searches = {k: v for k, v in self._searches.items() if v[0] > now}
            while len(self._searches) > SEARCHES_KEPT:
                del self._searches[next(iter(self._searches))]
        return result

    async def track(self, track_id: str) -> SpotifyTrack | None:
        """One track by id, or None if Spotify doesn't have it."""
        try:
            return _track(await self._get(f"/tracks/{track_id}", {"market": self._market}))
        except SpotifyNotFound:
            return None

    async def album(self, album_id: str) -> tuple[SpotifyAlbum, list[SpotifyTrack]]:
        """An album and its songs in order, leaving out any that can't play here. Catalogue
        data, so unlike a playlist it needs no connected account."""
        try:
            data = await self._get(f"/albums/{album_id}", {"market": self._market})
            album = _album(data)
            page, items = data["tracks"], []
            while True:
                items += page["items"]
                if not page.get("next") or len(items) >= IMPORT_LIMIT:
                    break
                page = await self._get(
                    f"/albums/{album_id}/tracks",
                    {"limit": IMPORT_PAGE, "offset": len(items), "market": self._market},
                )
        except SpotifyNotFound:
            raise SpotifyNotFound("Spotify doesn't have that album.") from None
        tracks = [
            # Album listings leave the album off each song, so it comes from the album.
            _track({**item, "album": {"name": album.name, "images": data.get("images")}})
            for item in items[:IMPORT_LIMIT]
            if item and item.get("id") and item.get("is_playable", True)
        ]
        return album, tracks

    async def playlist(self, db: AsyncSession, playlist_id: str) -> tuple[str, list[SpotifyTrack]]:
        """A playlist's name and tracks, read with the connected account. Spotify only allows
        this for playlists that account owns or collaborates on."""
        token = await self.user_token(db)
        try:
            about = await self._get(
                f"/playlists/{playlist_id}", {"fields": "name"}, user_token=token
            )
            tracks: list[SpotifyTrack] = []
            for offset in range(0, IMPORT_LIMIT, IMPORT_PAGE):
                page = await self._get(
                    f"/playlists/{playlist_id}/items",
                    {"limit": IMPORT_PAGE, "offset": offset, "market": self._market},
                    user_token=token,
                )
                for row in page["items"]:
                    # Spotify renamed "track" to "item" in 2026; accept either.
                    item = row.get("item") or row.get("track")
                    playable = item and item.get("is_playable", True)
                    if playable and item.get("type", "track") == "track" and item.get("id"):
                        tracks.append(_track(item))
                if not page.get("next"):
                    break
        except SpotifyNotFound:
            raise SpotifyNotFound("Spotify doesn't have that playlist.") from None
        except SpotifyForbidden:
            raise SpotifyForbidden(
                "Spotify won't share that playlist. GuildFM can only import playlists the "
                "connected account owns or collaborates on."
            ) from None
        return about["name"], tracks

    # Connecting a person's account

    def authorize_url(self) -> str:
        now = self._clock()
        self._states = {state: at for state, at in self._states.items() if at > now - STATE_SECONDS}
        state = secrets.token_urlsafe(24)
        self._states[state] = now
        query = {
            "response_type": "code",
            "client_id": self._id,
            "scope": SCOPES,
            "redirect_uri": self._redirect_uri,
            "state": state,
            "show_dialog": "true",
        }
        return f"{ACCOUNTS}/authorize?{urlencode(query)}"

    def accept_state(self, state: str) -> bool:
        """Whether `state` came from one of GuildFM's own recent connect links. Single use."""
        created = self._states.pop(state, None)
        return created is not None and created > self._clock() - STATE_SECONDS

    async def connect(self, db: AsyncSession, code: str) -> SpotifyAccount:
        tokens = await self._token(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": self._redirect_uri}
        )
        me = await self._get("/me", user_token=tokens["access_token"])
        now = self._clock()
        account = SpotifyAccount(
            id=1,
            spotify_user_id=me["id"],
            display_name=me.get("display_name") or me["id"],
            refresh_token=tokens["refresh_token"],
            access_token=tokens["access_token"],
            access_expires_at=now + tokens["expires_in"],
            connected_at=now,
        )
        account = await db.merge(account)
        await db.commit()
        return account

    async def user_token(self, db: AsyncSession) -> str:
        """A working token for the connected account, refreshed when it's about to run out."""
        account = await db.get(SpotifyAccount, 1)
        if account is None:
            raise NotConnected("No Spotify account is connected.")
        if account.access_token and account.access_expires_at > self._clock() + 60:
            return account.access_token
        try:
            tokens = await self._token(
                {"grant_type": "refresh_token", "refresh_token": account.refresh_token}
            )
        except NotConnected:
            await db.delete(account)
            await db.commit()
            raise
        account.access_token = tokens["access_token"]
        account.access_expires_at = self._clock() + tokens["expires_in"]
        account.refresh_token = tokens.get("refresh_token") or account.refresh_token
        await db.commit()
        return account.access_token

    async def playlist_count(self, db: AsyncSession) -> int:
        data = await self._get("/me/playlists", {"limit": 1}, user_token=await self.user_token(db))
        return data["total"]


async def remember(db: AsyncSession, tracks: list[SpotifyTrack]) -> None:
    """Keep track details locally, updating any that changed."""
    if not tracks:
        return
    rows = [
        {
            "id": track.id,
            "title": track.title,
            "artists": track.artists,
            "album": track.album,
            "duration_ms": track.duration_ms,
            "explicit": track.explicit,
            "art_url": track.art_url,
        }
        for track in {track.id: track for track in tracks}.values()
    ]
    statement = insert(Track).values(rows)
    updated = {column: statement.excluded[column] for column in rows[0] if column != "id"}
    updated["updated_at"] = func.now()
    await db.execute(statement.on_conflict_do_update(index_elements=["id"], set_=updated))
    await db.commit()
