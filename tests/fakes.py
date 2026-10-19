import base64
import json
import re
from typing import NamedTuple
from urllib.parse import parse_qsl

import httpx2

from guildfm.speakers import (
    QUEUE_URI,
    QueueItem,
    Room,
    Snapshot,
    SpeakersRefused,
    SpeakersUnavailable,
    Track,
)

COORDINATOR = "RINCON_LOUNGE"


def spotify_id(name: str) -> str:
    """A made-up Spotify track id. Real ones are 22 letters and digits."""
    return name.ljust(22, "x")


RADIO = "x-sonosapi-radio:sonos%3a3094?sid=303&flags=8232&sn=8"


class PlayedClip(NamedTuple):
    room: str
    url: str
    volume: int
    music: str  # what the music was doing while it played: PLAYING, PAUSED_PLAYBACK...
    start: object = None  # the starting line the rooms playing it share


class FakeSpeakers:
    """An office Sonos system in memory: three rooms, one of them a TV soundbar."""

    def __init__(self) -> None:
        self.available = True
        self.transport = "PLAYING"
        self.media_uri = RADIO
        self.queue: list[QueueItem] = []
        self.position: int | None = None
        self.outside_track: Track | None = Track(
            uri="x-sonos-http:sonos%3aradio-track", title="Nobody's Business", artist="Maxus",
            album="", art_url=None, duration=0, position=121,
        )  # fmt: skip
        self.rooms = {
            COORDINATOR: Room(COORDINATOR, "Upstairs Lounge", "Sonos One", 20, True, False),
            "RINCON_KITCHEN": Room("RINCON_KITCHEN", "Kitchen", "Sonos One SL", 19, True, False),
            "RINCON_ARC": Room("RINCON_ARC", "Downstairs", "Sonos Arc", 14, True, False),
        }
        self.took_over: list[list[QueueItem]] = []
        self.track_position = 3  # seconds into the current queued track, out of 200
        self.clips: list[PlayedClip] = []
        self.refusing_clips: set[str] = set()  # rooms that turn overlay clips down
        self.queue_refuses_clips = False  # MP3s from GuildFM can't go in the queue
        self.crossfade = False
        self.wont_start: str | None = None  # a song's key that never starts, however often tried
        self.played: list[QueueItem] = []  # what played to the end from the queue, in order

    # Things that happen in the office

    def someone_plays_radio(self) -> None:
        self.media_uri = RADIO
        self.transport = "PLAYING"

    def someone_pauses(self) -> None:
        self.transport = "PAUSED_PLAYBACK"

    def tv_turns_on(self) -> None:
        arc = self.rooms["RINCON_ARC"]
        self.rooms["RINCON_ARC"] = Room(arc.uid, arc.name, arc.model, arc.volume, False, True)

    # The SpeakerSystem interface

    def _check(self) -> None:
        if not self.available:
            raise SpeakersUnavailable("No Sonos speakers found on the network.")

    def snapshot(self, full: bool) -> Snapshot:
        self._check()
        ours = self.media_uri == QUEUE_URI.format(uid=COORDINATOR)
        track = self.outside_track
        if ours:
            item = self.queue[self.position - 1] if self.position else None
            track = item and Track(item.uri, "Queued track", "", "", None, 200, self.track_position)
        return Snapshot(
            coordinator_uid=COORDINATOR,
            coordinator_name="Upstairs Lounge",
            transport=self.transport,
            media_uri=self.media_uri,
            track=track,
            queue_position=self.position if ours else None,
            group_volume=round(sum(r.volume for r in self.rooms.values()) / len(self.rooms)),
            rooms=list(self.rooms.values()) if full else [],
        )

    def play(self) -> None:
        self._check()
        self.transport = "PLAYING"

    def pause(self) -> None:
        self._check()
        self.transport = "PAUSED_PLAYBACK"

    def skip(self) -> None:
        self._check()
        if self.position and self.position < len(self.queue):
            self.song_ends()
        else:
            self.transport = "STOPPED"

    def song_ends(self) -> None:
        """The speakers move on to the next thing in their queue, as at the end of a song."""
        if self.position:
            self.played.append(self.queue[self.position - 1])
        if self.position and self.position < len(self.queue):
            self.position += 1
            self.track_position = 0
        else:
            self.transport = "STOPPED"

    def next_song_fails(self) -> None:
        """The song ends and the next one won't play: the speakers stop, and go back to the start
        of their queue, as Sonos does."""
        self.transport = "STOPPED"
        self.position = 1 if self.queue else None
        self.track_position = 0

    def on_clip(self) -> bool:
        """Whether an MP3 from GuildFM is playing from the queue, such as the DJ."""
        ours = self.media_uri == QUEUE_URI.format(uid=COORDINATOR)
        return ours and bool(self.position) and self.queue[self.position - 1].uri.startswith("http")

    def set_group_volume(self, volume: int) -> None:
        self._check()
        for uid, room in self.rooms.items():
            self.rooms[uid] = Room(
                room.uid, room.name, room.model, volume, room.in_group, room.on_tv
            )

    def set_crossfade(self, on: bool) -> None:
        self._check()
        self.crossfade = on

    def set_room_volume(self, uid: str, volume: int) -> None:
        self._check()
        room = self.rooms[uid]
        self.rooms[uid] = Room(room.uid, room.name, room.model, volume, room.in_group, room.on_tv)

    def take_over(self, items: list[QueueItem]) -> None:
        self._check()
        self.took_over.append(list(items))
        self.queue = list(items)
        self.position = 1
        self.media_uri = QUEUE_URI.format(uid=COORDINATOR)
        self.transport = "PLAYING"

    def add_next(self, item: QueueItem) -> int:
        self._check()
        position = (self.position or 0) + 1
        self.queue.insert(position - 1, item)
        return position

    def add_at(self, item: QueueItem, position: int) -> int:
        self._check()
        if self.queue_refuses_clips and item.uri.startswith("http"):
            raise SpeakersRefused("The speakers wouldn't do that (ERROR_PLAYBACK).")
        self.queue.insert(position - 1, item)
        if self.position and position <= self.position:
            self.position += 1
        return position

    def remove(self, position: int) -> None:
        self._check()
        del self.queue[position - 1]
        if self.position and position < self.position:
            self.position -= 1

    def play_position(self, position: int) -> None:
        self._check()
        if self.queue[position - 1].key == self.wont_start:
            self.next_song_fails()
            return
        self.position = position
        self.track_position = 0
        self.transport = "PLAYING"

    def play_clip(self, uid: str, url: str, volume: int, start=None) -> None:
        self._check()
        if uid in self.refusing_clips:
            raise SpeakersRefused(f"{self.rooms[uid].name} wouldn't play it (ERROR_PLAYBACK).")
        self.clips.append(PlayedClip(uid, url, volume, self.transport, start))

    def own_address(self) -> str:
        return "127.0.0.1"


def mp3(seconds: float) -> bytes:
    """A made-up MP3 lasting about `seconds`: an ID3 tag, then silent MPEG-1 Layer III frames
    at 128 kbps and 44.1 kHz, 417 bytes and 1152 samples each."""
    frame = b"\xff\xfb\x90\x00" + bytes(413)
    return b"ID3\x03\x00\x00\x00\x00\x00\x00" + frame * round(seconds * 44100 / 1152)


class FakeOpenAI:
    """OpenAI's text to speech and text models, as a transport for httpx2."""

    def __init__(self) -> None:
        self.requests: list[dict] = []  # text to speech
        self.status = 200
        self.seconds = 3.0  # how long each clip it makes lasts
        self.asked: list[dict] = []  # the text model
        self.picks: list[dict] = []  # songs it suggests for a station
        self.line = {"script": "That was lovely. Here's another."}
        self.news = "Nothing notable in music news this week."
        self.down = False  # the text model fails
        self.images: list[dict] = []  # covers it's asked to paint
        self.images_down = False  # the image model fails

    def asked_for(self, name: str) -> list[dict]:
        """Requests for answers in the named format, such as "picks" or "dj_line"."""
        return [b for b in self.asked if b.get("text", {}).get("format", {}).get("name") == name]

    def _answer(self, body: dict) -> httpx2.Response:
        self.asked.append(body)
        if self.down:
            return httpx2.Response(500, json={"error": {"message": "nope"}})
        name = body.get("text", {}).get("format", {}).get("name")
        if name == "picks":
            text = json.dumps({"songs": self.picks})
        elif name == "dj_line":
            text = json.dumps(self.line)
        else:
            text = self.news
        output = [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": text}]},
        ]
        return httpx2.Response(200, json={"status": "completed", "output": output})

    def painted(self, number: int) -> bytes:
        """The made-up WebP it sends for the `number`th cover, from 1."""
        return b"RIFF\x00\x00\x00\x00WEBP" + f"cover {number}".encode()

    def _image(self, body: dict) -> httpx2.Response:
        self.images.append(body)
        if self.images_down:
            return httpx2.Response(500, json={"error": {"message": "nope"}})
        picture = base64.b64encode(self.painted(len(self.images))).decode()
        return httpx2.Response(200, json={"data": [{"b64_json": picture}]})

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/v1/responses":
            return self._answer(json.loads(request.content))
        if request.url.path == "/v1/images/generations":
            return self._image(json.loads(request.content))
        assert request.url.path == "/v1/audio/speech"
        self.requests.append(json.loads(request.content))
        if self.status != 200:
            return httpx2.Response(self.status, json={"error": {"message": "nope"}})
        return httpx2.Response(
            200, content=mp3(self.seconds), headers={"content-type": "audio/mpeg"}
        )


class FakeElevenLabs:
    """ElevenLabs' voices and text to speech, as a transport for httpx2."""

    def __init__(self) -> None:
        self.voices = [
            {"voice_id": "guildbert01", "name": "Guildbert", "category": "generated"},
            {"voice_id": "aurora02", "name": "aurora", "category": "cloned"},
        ]
        self.requests: list[dict] = []  # text to speech: the voice, model and text
        self.status = 200
        self.detail: dict | None = None  # sent with an error status
        self.seconds = 4.0
        # The account's credits this month, or None for a key that can't read them.
        self.subscription: dict | None = {
            "tier": "creator",
            "character_count": 2235,
            "character_limit": 131000,
            "next_character_count_reset_unix": 1794825022,
        }

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        assert request.headers["xi-api-key"] == "eleven-test"
        if request.url.path == "/v1/user/subscription":
            if self.subscription is None:
                detail = {"status": "missing_permissions", "message": "user_read"}
                return httpx2.Response(401, json={"detail": detail})
            return httpx2.Response(200, json=self.subscription)
        if request.url.path == "/v2/voices":
            assert request.url.params["voice_type"] == "personal"
            return httpx2.Response(200, json={"voices": self.voices, "has_more": False})
        voice = request.url.path.removeprefix("/v1/text-to-speech/")
        self.requests.append({"voice": voice, **json.loads(request.content)})
        if self.status != 200:
            return httpx2.Response(self.status, json={"detail": self.detail or {}})
        return httpx2.Response(
            200, content=mp3(self.seconds), headers={"content-type": "audio/mpeg"}
        )


class FakeWeather:
    """Open-Meteo's place search and forecast, as a transport for httpx2."""

    def __init__(self) -> None:
        self.code = 61  # light rain
        self.temperature = 9.4
        self.asked = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.asked += 1
        if request.url.host == "geocoding-api.open-meteo.com":
            places = [
                {"name": "Carlisle", "admin1": "Pennsylvania", "country_code": "US",
                 "latitude": 40.2, "longitude": -77.2},
                {"name": "Carlisle", "admin1": "England", "admin2": "Cumbria",
                 "country_code": "GB", "latitude": 54.9, "longitude": -2.9},
            ]  # fmt: skip
            return httpx2.Response(200, json={"results": places})
        assert request.url.params["latitude"] == "54.9", "should be the Carlisle in Cumbria"
        current = {
            "temperature_2m": self.temperature,
            "apparent_temperature": self.temperature - 2,
            "weather_code": self.code,
            "wind_speed_10m": 14.0,
            "is_day": 1,
        }
        return httpx2.Response(200, json={"current": current})


class FakeSpotify:
    """Spotify's accounts service and Web API, as a transport for httpx2."""

    def __init__(self) -> None:
        self.tracks = [
            self.track("dreams", "Dreams", "Fleetwood Mac", "Rumours"),
            self.track("gyow", "Go Your Own Way", "Fleetwood Mac", "Rumours"),
            self.track("humble", "HUMBLE.", "Kendrick Lamar", "DAMN.", explicit=True),
        ] + [
            self.track(f"fm{number}", f"Song {number}", "Fleetwood Mac", "Tusk")
            for number in range(1, 22)
        ]
        # Albums: name, artist, release date and songs. Tusk's last song can't play here.
        self.albums = {
            spotify_id("rumours"): ("Rumours", "Fleetwood Mac", "1977-02-04", ["dreams", "gyow"]),
            spotify_id("tusk"): (
                "Tusk", "Fleetwood Mac", "1979-10-12", [f"fm{n}" for n in range(1, 22)]
            ),
            spotify_id("damn"): ("DAMN.", "Kendrick Lamar", "2017", ["humble"]),
        }  # fmt: skip
        self.unplayable = {spotify_id("fm21")}
        # Playlists the connected account owns, and one it doesn't (like Spotify's own).
        self.playlists = {spotify_id("classics"): ("Office Classics", ["dreams", "gyow", "fm1"])}
        self.not_ours = {spotify_id("editorial")}
        self.token_requests: list[str] = []
        self.refresh_fails = False
        # Real Spotify's search pages overlap now and then: each page after the first starts
        # this many tracks early, repeating the end of the page before.
        self.overlap = 0
        self.busy = False

    @staticmethod
    def track(name: str, title: str, artist: str, album: str, explicit: bool = False):
        track_id = spotify_id(name)
        images = [
            {"url": f"https://i.scdn.co/{track_id}-{size}", "width": size}
            for size in (640, 300, 64)
        ]
        return {
            "id": track_id,
            "name": title,
            "artists": [{"name": artist}],
            "album": {"name": album, "images": images},
            "duration_ms": 200_000,
            "explicit": explicit,
        }

    @staticmethod
    def images(item_id: str) -> list[dict]:
        return [
            {"url": f"https://i.scdn.co/{item_id}-{size}", "width": size} for size in (640, 300, 64)
        ]

    def _album_info(self, album_id: str) -> dict:
        name, artist, released, songs = self.albums[album_id]
        return {
            "id": album_id,
            "name": name,
            "artists": [{"name": artist}],
            "images": self.images(album_id),
            "release_date": released,
            "album_type": "album",
            "total_tracks": len(songs),
        }

    # Real Spotify lists 50 of an album's songs with the album; fewer here, to need paging.
    ALBUM_PAGE = 10

    def _album_songs(self, album_id: str, offset: int, limit: int) -> dict:
        by_id = {t["id"]: t for t in self.tracks}
        songs = [by_id[spotify_id(name)] for name in self.albums[album_id][3]]
        # Album listings leave the album off each song, and say whether it plays here.
        items = [
            {key: value for key, value in song.items() if key != "album"}
            | {"is_playable": song["id"] not in self.unplayable}
            for song in songs[offset : offset + limit]
        ]
        return {"items": items, "next": "more" if offset + limit < len(songs) else None}

    def _album(self, path: str, params: dict) -> httpx2.Response:
        parts = path.split("/")  # "", "v1", "albums", id, maybe "tracks"
        album_id = parts[3]
        if album_id not in self.albums:
            return httpx2.Response(404)
        if len(parts) > 4:
            offset, limit = int(params["offset"]), int(params["limit"])
            return httpx2.Response(200, json=self._album_songs(album_id, offset, limit))
        body = self._album_info(album_id) | {
            "tracks": self._album_songs(album_id, 0, self.ALBUM_PAGE)
        }
        return httpx2.Response(200, json=body)

    def _search(self, params) -> dict:
        # Field filters like artist:"Fleetwood Mac" and track:"Dreams", then loose words.
        fields = dict(re.findall(r'(\w+):"([^"]*)"', params["q"].lower()))
        words = re.sub(r'\w+:"[^"]*"', "", params["q"].lower()).split()
        artist, title = fields.get("artist"), fields.get("track")
        matches = [
            t
            for t in self.tracks
            if (artist is None or t["artists"][0]["name"].lower() == artist)
            and (title is None or t["name"].lower() == title)
            and all(w in f"{t['name']} {t['artists'][0]['name']}".lower() for w in words)
        ]
        offset, limit = int(params["offset"]), int(params["limit"])
        assert limit <= 10, "development-mode apps can't ask for more than 10"
        start = max(0, offset - self.overlap) if offset else 0
        page = [
            t | {"is_playable": t["id"] not in self.unplayable}
            for t in matches[start : start + limit]
        ]
        result = {
            "tracks": {"items": page, "next": "more" if offset + limit < len(matches) else None}
        }
        if "artist" in params["type"].split(","):
            names = sorted({t["artists"][0]["name"] for t in matches})
            result["artists"] = {
                "items": [{"id": n.lower(), "name": n, "images": []} for n in names]
            }
        if "album" in params["type"].split(","):
            albums = [
                self._album_info(album_id)
                for album_id, (name, by, _, _) in self.albums.items()
                if (artist is None or by.lower() == artist)
                and all(w in f"{name} {by}".lower() for w in words)
            ]
            result["albums"] = {"items": albums[:limit]}
        return result

    def _playlist(self, path: str, params: dict) -> httpx2.Response:
        parts = path.split("/")  # "", "v1", "playlists", id, maybe "items"
        playlist_id, items = parts[3], len(parts) > 4
        if playlist_id in self.not_ours:
            # Spotify shares only the name of playlists the account doesn't own.
            return (
                httpx2.Response(403)
                if items
                else httpx2.Response(200, json={"name": "All Out 80s"})
            )
        if playlist_id not in self.playlists:
            return httpx2.Response(404)
        name, names = self.playlists[playlist_id]
        if not items:
            return httpx2.Response(200, json={"name": name})
        by_id = {t["id"]: t for t in self.tracks}
        rows = [{"item": by_id[spotify_id(n)]} for n in names]
        # Podcast episodes and gaps get left out of an import.
        rows += [{"item": {"type": "episode", "id": "ep1"}}, {"item": None}]
        offset, limit = int(params["offset"]), int(params["limit"])
        page = rows[offset : offset + limit]
        return httpx2.Response(
            200, json={"items": page, "next": "more" if offset + limit < len(rows) else None}
        )

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/api/token":
            form = dict(parse_qsl(request.content.decode()))
            self.token_requests.append(form["grant_type"])
            if form["grant_type"] == "refresh_token" and self.refresh_fails:
                return httpx2.Response(400, json={"error": "invalid_grant"})
            body = {"access_token": f"{form['grant_type']}-token", "expires_in": 3600}
            if form["grant_type"] == "authorization_code":
                body["refresh_token"] = "refresh-1"
            return httpx2.Response(200, json=body)
        if self.busy:
            return httpx2.Response(429, headers={"Retry-After": "7"})
        if path.startswith("/v1/playlists/"):
            return self._playlist(path, dict(request.url.params))
        if path.startswith("/v1/albums/"):
            return self._album(path, dict(request.url.params))
        if path.startswith("/v1/tracks/"):
            found = [t for t in self.tracks if t["id"] == path.rsplit("/", 1)[-1]]
            return httpx2.Response(200, json=found[0]) if found else httpx2.Response(404)
        if path == "/v1/search":
            return httpx2.Response(200, json=self._search(dict(request.url.params)))
        if path == "/v1/me":
            return httpx2.Response(200, json={"id": "office", "display_name": "Office Spotify"})
        if path == "/v1/me/playlists":
            return httpx2.Response(200, json={"total": 7, "items": []})
        return httpx2.Response(404)
