"""The demo office: GuildFM on the tests' fakes, with the office's six rooms and everything in
cast.py, set up as a Tuesday morning in progress.

The music stands still: the speakers never move on from the song they're playing, so every
screenshot sees the same moment. Some screens only show in other states, such as someone taking
over from the Sonos app, so the office moves through PHASES, in order, between batches of
screenshots."""

import asyncio
import base64
import dataclasses
import io
import itertools
import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2
from fastapi import FastAPI
from PIL import Image
from sqlalchemy import select

from guildfm.ai import AIClient
from guildfm.awareness import Awareness
from guildfm.config import ROOT, Settings
from guildfm.main import create_app
from guildfm.models import (
    AnnouncementPlay,
    Lineup,
    Play,
    Playlist,
    PlaylistKind,
    PlaylistTrack,
    SpotifyAccount,
    Track,
)
from guildfm.speakers import QUEUE_URI, Room, Snapshot, spotify_track_id
from guildfm.speakers import Track as SpeakerTrack
from guildfm.speech import SpeechClient
from guildfm.spotify import SpotifyClient
from tests.fakes import (
    COORDINATOR,
    RADIO,
    FakeElevenLabs,
    FakeOpenAI,
    FakeSpeakers,
    FakeSpotify,
    FakeWeather,
)
from tools.screenshots.cast import (
    DEMO,
    DJS,
    LINEUPS,
    PASSWORD,
    PEOPLE,
    STATIONS,
    slug,
)

# Tuesday 13 October 2026, 11:24 in the office (British Summer Time).
MOMENT = datetime(2026, 10, 13, 10, 24, tzinfo=UTC)
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
ART = "/media/demo-art"  # where the songs' artwork is served from

# The office's states, in order. Screenshots are taken in the first one unless they say.
PHASES = [
    "morning",  # as set up: a request playing, Office Classics filling the gaps
    "lineup",  # Office Day put on
    "drafts",  # three jingles made for Friday Feeling, waiting to be kept or turned down
    "takeover",  # someone has put the radio on from the Sonos app
    "monitor",  # monitor mode on
]


def catalogue() -> dict[str, Any]:
    return json.loads((DEMO / "catalogue.json").read_text())


def all_songs(found: dict[str, Any]) -> list[dict[str, Any]]:
    return found["songs"] + [s for album in found["albums"] for s in album["songs"]]


def lengths(found: dict[str, Any]) -> dict[str, int]:
    """Every song's length in seconds, by its id."""
    return {s["id"]: s["duration_ms"] // 1000 for s in all_songs(found)}


def songs_by_id(found: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in all_songs(found)}


def art(item_id: str) -> list[dict[str, Any]]:
    return [{"url": f"{ART}/{item_id}.jpg", "width": 400}]


def office_time(day: date, clock: str) -> datetime:
    """A time in the office, which is an hour ahead of UTC in October."""
    hour, minute = map(int, clock.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC) - timedelta(hours=1)


class DemoSpeakers(FakeSpeakers):
    """The office's six rooms, all in one group, quiet until GuildFM takes over. Songs report
    their real title and length."""

    def __init__(self, songs: dict[str, dict[str, Any]]) -> None:
        super().__init__()
        self.transport = "STOPPED"
        self.outside_track = None
        self._songs = songs

        def room(uid: str, name: str, model: str, volume: int) -> Room:
            return Room(uid, name, model, volume, True, False)

        self.rooms = {
            COORDINATOR: room(COORDINATOR, "Upstairs Lounge", "Sonos One", 22),
            "RINCON_ARC": room("RINCON_ARC", "Downstairs", "Sonos Arc", 18),
            "RINCON_ENTRANCE": room("RINCON_ENTRANCE", "Entrance", "Sonos One", 14),
            "RINCON_KITCHEN": room("RINCON_KITCHEN", "Kitchen", "Sonos One SL", 25),
            "RINCON_POD": room("RINCON_POD", "Pod", "Sonos One SL", 16),
            "RINCON_DONUT": room("RINCON_DONUT", "Donut Shop", "Sonos One", 20),
        }

    def snapshot(self, full: bool) -> Snapshot:
        snapshot = super().snapshot(full)
        ours = self.media_uri == QUEUE_URI.format(uid=COORDINATOR)
        track_id = spotify_track_id(snapshot.track.uri) if ours and snapshot.track else None
        song = self._songs.get(track_id)
        if song is None:
            return snapshot
        track = dataclasses.replace(
            snapshot.track,
            title=song["name"],
            artist=", ".join(song["artists"]),
            album=song["album"]["name"],
            duration=song["duration_ms"] // 1000,
        )
        return dataclasses.replace(snapshot, track=track)

    def playing_id(self) -> str | None:
        item = self.queue[self.position - 1] if self.position else None
        return item and spotify_track_id(item.uri)

    def someone_plays_radio(self) -> None:
        super().someone_plays_radio()
        self.outside_track = SpeakerTrack(
            uri=RADIO, title="BBC Radio 2", artist="", album="", art_url=None, duration=0,
            position=0,
        )  # fmt: skip


class DemoSpotify(FakeSpotify):
    """Spotify, knowing only the songs, artists and albums fetch.py gathered."""

    def __init__(self, found: dict[str, Any]) -> None:
        super().__init__()

        def item(song: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": song["id"],
                "name": song["name"],
                "artists": [{"name": name} for name in song["artists"]],
                "album": {"name": song["album"]["name"], "images": art(song["album"]["id"])},
                "duration_ms": song["duration_ms"],
                "explicit": song["explicit"],
            }

        self.tracks = [item(song) for song in {s["id"]: s for s in all_songs(found)}.values()]
        self.albums = {
            album["id"]: (
                album["name"],
                ", ".join(album["artists"]),
                album["release_date"],
                [song["id"] for song in album["songs"]],
            )
            for album in found["albums"]
        }
        self.unplayable = set()
        self.playlists = {}
        self.artist_art = {artist["name"]: artist["id"] for artist in found["artists"]}

    @staticmethod
    def images(item_id: str) -> list[dict]:
        return art(item_id)

    def _search(self, params) -> dict:
        result = super()._search(params)
        for artist in result.get("artists", {}).get("items", []):
            if artist["name"] in self.artist_art:
                artist["images"] = art(self.artist_art[artist["name"]])
        return result


# What each station picks, as (title asked for in cast.py, why it fits), by a word from its
# description.
PICKS = {
    "Xennials": [
        ("Don't You (Forget About Me)", "Pure Breakfast Club nostalgia"),
        ("Common People", "Britpop with a story to tell"),
        ("Girls Just Want to Have Fun", "An 80s singalong to lift the room"),
        ("Wonderwall", "Everyone knows the words"),
        ("Everybody Wants To Rule The World", "Big 80s synths, easy to work to"),
        ("Torn", "A late-90s favourite"),
        ("Song 2", "Two minutes of energy"),
        ("Sweet Dreams (Are Made of This)", "A synth-pop classic"),
        ("Bitter Sweet Symphony", "Those strings, after something upbeat"),
        ("Toxic", "Early-2000s pop at its best"),
        ("Don't Look Back In Anger", "A proper Britpop anthem"),
        ("Crazy In Love", "Horns to wake up the afternoon"),
        ("Take On Me", "The keyboard riff everyone hums"),
        ("Wake Me Up Before You Go-Go", "Pure 80s fun"),
    ],
    "acoustic": [
        ("Fast Car", "A gentle start to the morning"),
        ("Banana Pancakes", "Lazy-morning acoustic"),
        ("Bloom", "Soft and warm"),
        ("Better Together", "Easy listening with a smile"),
        ("Riptide", "A ukulele to brighten things"),
        ("Landslide", "Quiet and lovely"),
        ("Songbird", "Christine McVie at her gentlest"),
        ("Rhiannon", "A little more pace as the office fills"),
    ],
    "Disco": [
        ("Le Freak", "Disco to start the weekend early"),
        ("Good Times", "That bassline"),
        ("I Feel Love", "Pure dance floor"),
        ("Get Lucky", "Modern disco"),
        ("Uptown Funk", "Feel-good funk"),
        ("Can't Stop the Feeling!", "Impossible to sit still to"),
        ("Dancing Queen", "Friday is ABBA o'clock"),
    ],
}

# What the DJ says before a song, taking turns. {title} and {artist} are the song coming up.
LINES = [
    "[chuckles] Right then, that's the kettle on and the inbox ignored. Here's {artist} with "
    "{title}.",
    "Nine degrees and drizzle over Carlisle, so let's pretend it's summer. {title}, {artist}.",
    "That one goes out to whoever keeps nicking the good mugs from the kitchen. [laughs] Next "
    "up, {artist}.",
    "Bit of trivia for you: this next one nearly didn't make the album. Glad it did. It's {title}.",
    "Back to back on GuildFM, and no complaints from the Pod so far. {artist}, {title}.",
]

# Jingles the AI writes in the generator, taking turns.
IDEAS = [
    {"name": "Friday Disco Sting", "seconds": 7,
     "description": "A punchy disco sting: funky guitar, strings and handclaps, with a group of "
                    "singers chanting \"It's Friday Feeling!\" over the last bar."},
    {"name": "Mirrorball", "seconds": 9,
     "description": "A shimmering four-to-the-floor intro with a slap bass line, ending on a "
                    "big string stab and a choir singing \"Friday Feeling!\"."},
    {"name": "Weekend Countdown", "seconds": 6,
     "description": "Brassy funk horns counting down, then a bright female voice singing "
                    "\"Friday Feeling, on GuildFM!\"."},
]  # fmt: skip


class DemoOpenAI(FakeOpenAI):
    """OpenAI for the demo office: the covers fetch.py painted, songs from the catalogue for
    the stations, DJ lines about the song coming up, and jingle ideas."""

    def __init__(self, found: dict[str, Any]) -> None:
        super().__init__()
        names = {s["wanted"][0]: s for s in found["songs"]}
        self._picks = {
            word: [
                {"title": names[title]["name"], "artist": names[title]["artists"][0], "note": note}
                for title, note in songs
            ]
            for word, songs in PICKS.items()
        }
        self._lines = itertools.cycle(LINES)
        self.ideas = IDEAS
        self.heard = ["It's Friday Feeling!"]

    def _image(self, body: dict) -> httpx2.Response:
        named = re.match(r'Square cover art for "(.+?)"', body["prompt"])
        cover = DEMO / "covers" / f"{slug(named[1])}.webp" if named else None
        self.images.append(body)
        if cover is None or not cover.exists():
            return super()._image(body)
        picture = base64.b64encode(cover.read_bytes()).decode()
        return httpx2.Response(200, json={"data": [{"b64_json": picture}]})

    def painted(self, number: int) -> bytes:
        """A plain warm square, for anything the demo didn't bring a cover for."""
        picture = io.BytesIO()
        Image.new("RGB", (64, 64), (53, 43, 39)).save(picture, "WEBP")
        return picture.getvalue()

    def _answer(self, body: dict) -> httpx2.Response:
        name = body.get("text", {}).get("format", {}).get("name")
        if name == "picks":
            asked = body["input"]
            word = next((w for w in self._picks if w.lower() in asked.lower()), "Xennials")
            schema = body["text"]["format"]["schema"]["properties"]["songs"]["items"]
            idents = schema["properties"].get("ident", {}).get("enum", [])
            kind = "station" if "station" in idents else "system" if "system" in idents else None
            songs = [
                song | ({"ident": kind if number % 4 == 1 else "none"} if kind else {})
                for number, song in enumerate(self._picks[word])
            ]
            self.picks = songs
        elif name == "dj_line":
            coming = re.search(r'Up next: "(.+?)" by (.+?)\.(?: Why|\n|$)', body["input"])
            title, artist = (coming[1], coming[2]) if coming else ("this one", "GuildFM")
            title = title.split(" - ")[0]
            self.line = {"script": next(self._lines).format(title=title, artist=artist)}
        return super()._answer(body)


def fake(service) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(service))


def build(data: Path) -> tuple[FastAPI, DemoSpeakers]:
    """GuildFM for the demo office, keeping its data in `data`."""
    found = catalogue()

    settings = Settings(
        _env_file=None,
        openai_api_key="demo",
        spotify_client_id="demo",
        spotify_client_secret="demo",
        guildfm_secret_key="demo",
        guildfm_admin_username=PEOPLE[0].username,
        guildfm_admin_password=PASSWORD,
        data_dir=data,
        audio_loudness=None,
        web_dist=ROOT / "web" / "dist",
        port=PORT,
    )
    shutil.copytree(DEMO / "art", data / "media" / "demo-art")

    openai, elevenlabs = DemoOpenAI(found), FakeElevenLabs()
    # Jingles' plans sing the words the AI's ideas quote, so they're heard.
    elevenlabs.parts = [("[Intro]\n{groove}", 2), ("[Hook]\nIt's Friday Feeling!", 5)]

    def voices(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "api.elevenlabs.io":
            return elevenlabs(request)
        return openai(request)

    speakers = DemoSpeakers(songs_by_id(found))
    spotify = SpotifyClient(
        client_id="demo",
        client_secret="demo",
        redirect_uri=settings.spotify_redirect_uri,
        market="GB",
        http=fake(DemoSpotify(found)),
    )
    speech = SpeechClient(
        api_key="demo",
        model="gpt-4o-mini-tts",
        media_dir=data / "media",
        http=fake(voices),
        eleven_key="eleven-test",
    )
    ai = AIClient("demo", "gpt-6-astra", "low", http=fake(openai))
    app = create_app(
        settings,
        speakers,
        spotify,
        speech=speech,
        ai=ai,
        awareness=Awareness(ai, http=fake(FakeWeather())),
    )
    return app, speakers


class Visitor:
    """Someone in the office, signed in to the demo GuildFM."""

    def __init__(self, username: str) -> None:
        self.username = username
        self.http = httpx2.AsyncClient(base_url=f"{BASE}/api", timeout=30)
        self.id = 0

    async def call(self, method: str, path: str, body: Any = None, **options) -> Any:
        response = await self.http.request(method, path, json=body, **options)
        if response.status_code >= 400:
            raise RuntimeError(f"{self.username}: {method} {path}: {response.text}")
        return response.json() if response.content else None

    async def close(self) -> None:
        await self.http.aclose()


@dataclass
class Office:
    """The demo office once it's set up: GuildFM, its speakers, and who and what is in it."""

    app: FastAPI
    speakers: DemoSpeakers
    people: dict[str, Visitor] = field(default_factory=dict)
    song: dict[str, str] = field(default_factory=dict)  # song ids by the title in cast.py
    playlists: dict[str, int] = field(default_factory=dict)
    stations: dict[str, int] = field(default_factory=dict)
    lineups: dict[str, int] = field(default_factory=dict)
    # Anyone whose password isn't the usual one: people an admin added, with their temporary
    # password.
    passwords: dict[str, str] = field(default_factory=dict)

    async def close(self) -> None:
        await asyncio.gather(*(visitor.close() for visitor in self.people.values()))


async def seed(app: FastAPI, speakers: DemoSpeakers) -> Office:
    """Sets the office up: the people, songs, playlists, stations, line-ups and jingles, a
    playlist on with requests and votes, today's plays and the announcements."""
    found = catalogue()
    office = Office(app, speakers, song={s["wanted"][0]: s["id"] for s in found["songs"]})
    song, sessions = office.song, app.state.sessionmaker
    # Uploads are evened out with ffmpeg, as in the office. The jingle generator's and the
    # voices' fake MP3s are silent, so they're left as they are.
    app.state.settings.audio_loudness = -14.0

    async with sessions() as db:
        for s in found["songs"]:
            db.add(
                Track(
                    id=s["id"],
                    title=s["name"],
                    artists=", ".join(s["artists"]),
                    album=s["album"]["name"],
                    duration_ms=s["duration_ms"],
                    explicit=s["explicit"],
                    art_url=art(s["album"]["id"])[0]["url"],
                )
            )
        # Spotify was connected a month ago, so curators can import.
        db.add(
            SpotifyAccount(
                spotify_user_id="office",
                display_name="Office Spotify",
                refresh_token="demo",
                access_token="demo",
                access_expires_at=(MOMENT + timedelta(days=1)).timestamp(),
                connected_at=(MOMENT - timedelta(days=30)).timestamp(),
            )
        )
        await db.commit()

    await people(office)
    hannah, tom, grace = office.people["hannah"], office.people["tom"], office.people["grace"]

    # The announcement voice is GuildFM's own ElevenLabs voice, so emotions are offered.
    await hannah.call("PATCH", "/settings", {"announcement_voice": "elevenlabs:guildbert01"})

    await playlists(office)
    await stations(office)
    await jingles(office)
    for lineup in LINEUPS:
        made = await office.people[lineup.curator].call(
            "POST",
            "/lineups",
            {
                "name": lineup.name,
                "description": lineup.description,
                "slots": [
                    {"start": minutes(start), "end": minutes(end)} | slot_for(office, what)
                    for start, end, what in lineup.slots
                ],
            },
        )
        office.lineups[lineup.name] = made["id"]
    await app.state.covers.settle()
    async with sessions() as db:
        office_day = await db.get(Lineup, office.lineups["Office Day"])
        office_day.last_on_at = (MOMENT - timedelta(days=1)).timestamp()
        await db.commit()

    await tom.call("POST", f"/playlists/{office.playlists['Office Classics']}/play")
    await history(office)

    # Grace's request is on, near its end, so Owen's is already locked in as next.
    async def request(username: str, title: str) -> int:
        queue = await office.people[username].call("POST", "/queue", {"track_id": song[title]})
        return next(e["id"] for e in queue["waiting"] if e["track"]["id"] == song[title])

    await request("grace", "Mr. Blue Sky")
    await hannah.call("POST", "/playback/play")
    await request("owen", "September")
    await until(lambda: speakers.playing_id() == song["Mr. Blue Sky"])
    speakers.track_position = lengths(found)[song["Mr. Blue Sky"]] - 26
    await until_queue(hannah, lambda q: q["next"] is not None)

    requests = {
        title: await request(username, title)
        for username, title in [
            ("priya", "Dreams"),
            ("callum", "Golden Hour"),
            ("amara", "Heat Waves"),
            ("tom", "Don't Stop Me Now"),
            ("hannah", "Levitating"),
            ("ben", "Africa"),
        ]
    }
    votes = {
        "Dreams": {"owen": 1, "grace": 1, "amara": 1, "hannah": 1},
        "Golden Hour": {"ben": 1, "ellie": 1, "priya": 1},
        "Heat Waves": {"priya": 1, "callum": 1},
        "Don't Stop Me Now": {"owen": 1, "grace": 1, "ben": -1},
        "Africa": {"owen": -1, "priya": -1, "callum": 1},
    }
    for title, voters in votes.items():
        for username, value in voters.items():
            await office.people[username].call(
                "POST", f"/queue/{requests[title]}/vote", {"value": value}
            )

    queue = await grace.call("GET", "/queue")
    upcoming = queue["source"]["upcoming"]
    await office.people["owen"].call(
        "POST", "/source/vote", {"track_id": upcoming[1]["track"]["id"], "down": True}
    )

    await announcements(office)

    # The activity, spread over the last half hour rather than all just now.
    for number, item in enumerate(app.state.queue.activity):
        item["at"] = (MOMENT - timedelta(minutes=1 + number * 2.5)).timestamp()
    await app.state.queue.changed()

    # Something for the Status page's recent problems.
    logging.getLogger("guildfm.awareness").warning(
        "Couldn't get the weather for Carlisle, Cumbria, UK: Open-Meteo didn't answer in time."
    )
    return office


async def people(office: Office) -> None:
    """Everyone signs up and adds their photo; the admin makes curators curators, and adds the
    new starter, who hasn't signed in yet."""
    hannah = office.people["hannah"] = Visitor("hannah")
    await hannah.call("POST", "/auth/login", {"username": "hannah", "password": PASSWORD})
    for person in PEOPLE:
        if person.new:
            made = await hannah.call(
                "POST", "/users", {"username": person.username, "display_name": person.name}
            )
            office.passwords[person.username] = made["temporary_password"]
            continue
        visitor = office.people.setdefault(person.username, Visitor(person.username))
        if person.role == "admin":
            me = await visitor.call("PATCH", "/me", {"display_name": person.name})
        else:
            me = await visitor.call(
                "POST",
                "/auth/register",
                {"username": person.username, "display_name": person.name, "password": PASSWORD},
            )
        visitor.id = me["id"]
        photo = DEMO / "people" / f"{person.username}.webp"
        if photo.exists():
            await visitor.call("PUT", "/me/avatar", content=photo.read_bytes())
        if person.role == "curator":
            await hannah.call("PATCH", f"/users/{visitor.id}", {"role": "curator"})
    # Ellie doesn't want her name read out.
    await office.people["ellie"].call("PATCH", "/me", {"announce_requests": False})


async def playlists(office: Office) -> None:
    song, people = office.song, office.people

    async def make(username: str, name: str, titles: list[str], shuffle: bool = False) -> None:
        made = await people[username].call("POST", "/playlists", {"name": name})
        for title in titles:
            await people[username].call(
                "POST", f"/playlists/{made['id']}/tracks", {"track_id": song[title]}
            )
        if shuffle:
            await people[username].call("PATCH", f"/playlists/{made['id']}", {"shuffle": True})
        office.playlists[name] = made["id"]

    await make("tom", "Office Classics", [
        "Walking On Sunshine", "Here Comes The Sun", "I Wanna Dance with Somebody",
        "Superstition", "Take On Me", "Dancing Queen", "Sweet Caroline", "Livin' On A Prayer",
        "Ain't No Mountain High Enough", "Mr. Brightside", "Shut Up and Dance",
        "Wake Me Up Before You Go-Go", "Billie Jean", "Lovely Day", "Can't Stop the Feeling!",
        "Electric Feel", "Dog Days Are Over", "Golden", "Pompeii", "Uptown Funk",
    ])  # fmt: skip
    await make("hannah", "Lunchtime Singalongs", [
        "Sweet Caroline", "Livin' On A Prayer", "Don't Stop Me Now", "Mr. Brightside",
        "Take On Me", "Dancing Queen", "I Wanna Dance with Somebody", "Africa",
        "Wake Me Up Before You Go-Go", "Shut Up and Dance", "Don't Look Back In Anger",
        "Wonderwall", "Common People", "Girls Just Want to Have Fun", "Mr. Blue Sky",
        "Uptown Funk", "Song 2",
    ], shuffle=True)  # fmt: skip

    # An album, imported from its Spotify link.
    rumours = next(a for a in catalogue()["albums"] if a["wanted"][0] == "Rumours")
    made = await people["tom"].call(
        "POST", "/playlists/import", {"link": f"https://open.spotify.com/album/{rumours['id']}"}
    )
    office.playlists[made["name"]] = made["id"]

    # Best Voted has filled itself over the weeks.
    best = [
        ("Mr. Brightside", 14), ("Dancing Queen", 12), ("Don't Stop Me Now", 11),
        ("September", 11), ("Superstition", 10), ("Dreams", 9), ("Take On Me", 9),
        ("Wonderwall", 8), ("Uptown Funk", 8), ("Electric Feel", 7), ("Heat Waves", 7),
        ("Common People", 6),
    ]  # fmt: skip
    async with office.app.state.sessionmaker() as db:
        voted = await db.scalar(select(Playlist).where(Playlist.kind == PlaylistKind.BEST_VOTED))
        for position, (title, upvotes) in enumerate(best):
            db.add(
                PlaylistTrack(
                    playlist_id=voted.id,
                    track_id=song[title],
                    position=position,
                    added_at=(MOMENT - timedelta(days=30 - position)).timestamp(),
                    upvotes=upvotes,
                )
            )
        await db.commit()
        office.playlists[voted.name] = voted.id


async def stations(office: Office) -> None:
    """The stations, made by their curators, sharing Guildbert."""
    djs: dict[str, int] = {}
    for station in STATIONS:
        maker = office.people[station.curator]
        fields: dict[str, Any] = {
            "name": station.name,
            "description": station.description,
            "global_awareness": station.global_awareness,
            "jingles": station.jingles,
            "crossfade": station.crossfade,
            "dj": station.dj is not None,
        }
        if station.dj:
            dj = DJS[station.dj]
            fields |= {
                "dj_id": djs.get(dj.name),
                "dj_name": dj.name,
                "personality": dj.personality,
                "voice": dj.voice,
                "talk_every": station.talk_every,
                "talk_unit": station.talk_unit,
                "style": station.style,
            }
        made = await maker.call("POST", "/stations", fields)
        office.stations[station.name] = made["id"]
        if station.dj:
            djs[station.dj] = made["dj_id"]
    for station in await office.people["hannah"].call("GET", "/stations"):
        office.stations.setdefault(station["name"], station["id"])


async def jingles(office: Office) -> None:
    """GuildFM's two system idents, and Xennials' Delight's six station idents, from
    assets/jingles."""
    folder = ROOT / "assets" / "jingles"

    async def upload(username: str, file: Path, station: str | None = None) -> None:
        # "Xennials_Delight_RB_Funk.mp3" is "R&B Funk"; "Guild_FM_2026-10-16T103325.mp3" is
        # "Guild FM".
        name = file.stem.replace("Xennials_Delight_", "").split("_2026")[0]
        params: dict[str, Any] = {"name": name.replace("_", " ").replace("RB", "R&B")}
        if station:
            params["station_id"] = office.stations[station]
        await office.people[username].call(
            "POST", "/jingles", content=file.read_bytes(), params=params
        )

    for file in sorted((folder / "System Idents").glob("*.mp3")):
        await upload("hannah", file)
    for station in STATIONS:
        if station.idents:
            for file in sorted((folder / "Station Idents" / station.idents).glob("*.mp3")):
                await upload(station.curator, file, station.name)


def minutes(clock: str) -> int:
    hour, minute = map(int, clock.split(":"))
    return hour * 60 + minute


def slot_for(office: Office, name: str) -> dict[str, int]:
    if name in office.stations:
        return {"station_id": office.stations[name]}
    return {"playlist_id": office.playlists[name]}


async def history(office: Office) -> None:
    """What's played: Morning Coffee as the office opened, then Office Classics with requests
    now and then, and yesterday's lunchtime singalongs and afternoon with Guildbert."""
    song, people = office.song, office.people
    today, yesterday = MOMENT.date(), MOMENT.date() - timedelta(days=1)
    morning = ["Fast Car", "Banana Pancakes", "Bloom", "Riptide", "Better Together",
               "Landslide", "Songbird", "Rhiannon"]  # fmt: skip
    since = [
        ("Lovely Day", None), ("Here Comes The Sun", None), ("Everywhere", "owen"),
        ("Superstition", None), ("Take On Me", "grace"), ("Dancing Queen", None),
        ("Go Your Own Way", "tom"), ("Sweet Caroline", None), ("Livin' On A Prayer", None),
        ("Little Lies", "ben"), ("Mr. Brightside", None), ("Electric Feel", "amara"),
        ("Billie Jean", None), ("Golden", "priya"),
    ]  # fmt: skip
    plays: list[Play] = []
    for number, title in enumerate(morning):
        plays.append(
            Play(
                track_id=song[title],
                station_id=office.stations["Morning Coffee"],
                played_at=(
                    office_time(today, "08:00") + timedelta(minutes=11 * number)
                ).timestamp(),
            )
        )
    start = MOMENT - timedelta(minutes=5 + 4 * len(since))
    for number, (title, username) in enumerate(since):
        plays.append(
            Play(
                track_id=song[title],
                requested_by=people[username].id if username else None,
                playlist_id=None if username else office.playlists["Office Classics"],
                played_at=(start + timedelta(minutes=4 * number)).timestamp(),
                upvotes=2 if username else 0,
            )
        )
    for number, title in enumerate(["Sweet Caroline", "Mr. Brightside", "Wonderwall"]):
        plays.append(
            Play(
                track_id=song[title],
                playlist_id=office.playlists["Lunchtime Singalongs"],
                played_at=(
                    office_time(yesterday, "12:10") + timedelta(minutes=4 * number)
                ).timestamp(),
            )
        )
    for number, title in enumerate(["Common People", "Torn", "Song 2"]):
        plays.append(
            Play(
                track_id=song[title],
                station_id=office.stations["Xennials' Delight"],
                played_at=(
                    office_time(yesterday, "16:40") + timedelta(minutes=4 * number)
                ).timestamp(),
            )
        )
    async with office.app.state.sessionmaker() as db:
        db.add_all(plays)
        await db.commit()


async def announcements(office: Office) -> None:
    hannah = office.people["hannah"]
    today = MOMENT.date()
    monday = today - timedelta(days=today.weekday())

    def on(day: date) -> str:
        return day.isoformat()

    scheduled = [
        {"text": "Lunch is ready in the kitchen. Come and get it while it's hot.",
         "rooms": None, "mode": "after", "start_date": on(monday), "at": "12:30",
         "repeat": "weekdays"},
        {"text": "Stand-up starts in five minutes in the Pod.",
         "rooms": [{"uid": "RINCON_POD", "name": "Pod"},
                   {"uid": COORDINATOR, "name": "Upstairs Lounge"}],
         "mode": "after", "start_date": on(monday), "at": "14:55", "repeat": "days",
         "days": ["mon", "wed", "fri"]},
        {"text": "Friday drinks start in ten minutes in the Donut Shop. First round's on us!",
         "rooms": None, "mode": "after", "start_date": on(monday), "at": "16:50",
         "repeat": "days", "days": ["fri"]},
        {"text": "This is a test of the fire alarm. There's no need to leave the building.",
         "rooms": None, "mode": "over", "start_date": on(today + timedelta(days=8)),
         "at": "10:00", "repeat": "once"},
        {"text": "Don't forget to fill in your timesheets before you go home.",
         "rooms": None, "mode": "after", "start_date": on(monday), "at": "16:30",
         "repeat": "days", "days": ["fri"], "active": False},
    ]  # fmt: skip
    for rule in scheduled:
        active = rule.pop("active", True)
        made = await hannah.call("POST", "/announcements", rule)
        if not active:
            await hannah.call("PATCH", f"/announcements/{made['id']}", {"active": False})

    def at(day: date, clock: str) -> float:
        return office_time(day, clock).timestamp()

    yesterday = today - timedelta(days=1)
    log_entries = [
        ("Lunch is ready in the kitchen. Come and get it while it's hot.", None,
         at(yesterday, "12:30"), None),
        ("Stand-up starts in five minutes in the Pod.", ["Pod", "Upstairs Lounge"],
         at(yesterday, "14:55"), None),
        ("The courier's at the front desk with a parcel for Owen.", ["Entrance"],
         at(yesterday, "15:12"), None),
        ("Cake in the kitchen for Ellie's birthday!", None, at(today, "07:45"),
         "Outside playback hours"),
    ]  # fmt: skip
    async with office.app.state.sessionmaker() as db:
        for text, rooms, played_at, problem in log_entries:
            db.add(AnnouncementPlay(text=text, rooms=rooms, played_at=played_at, problem=problem))
        await db.commit()


async def enter(office: Office, phase: str) -> None:
    """Moves the office on to `phase`, from the one before it."""
    people = office.people
    if phase == "lineup":
        await people["tom"].call("POST", f"/lineups/{office.lineups['Office Day']}/play")
        await until_queue(people["tom"], lambda q: bool(q["source"] and q["source"]["upcoming"]))
    elif phase == "drafts":
        station = office.stations["Friday Feeling"]
        for idea in IDEAS:
            await people["hannah"].call(
                "POST",
                "/jingles/drafts",
                {
                    "station_id": station,
                    "name": idea["name"],
                    "prompt": idea["description"],
                    "length": idea["seconds"],
                    "instrumental": False,
                },
            )

        async def made() -> bool:
            round = await people["hannah"].call("GET", f"/jingles/drafts?station_id={station}")
            return all(draft["status"] != "making" for draft in round["drafts"])

        for _ in range(300):
            if await made():
                break
            await asyncio.sleep(0.1)
    elif phase == "takeover":
        office.speakers.someone_plays_radio()
        for _ in range(150):
            state = await people["hannah"].call("GET", "/playback")
            if state["status"] == "overridden":
                break
            await asyncio.sleep(0.1)
    elif phase == "monitor":
        await people["hannah"].call("PUT", "/playback/monitor", {"on": True})


async def until(check, seconds: float = 15) -> None:
    for _ in range(int(seconds * 10)):
        if check():
            return
        await asyncio.sleep(0.1)
    raise TimeoutError("The demo office didn't get there in time")


async def until_queue(visitor: Visitor, check, seconds: float = 15) -> dict[str, Any]:
    for _ in range(int(seconds * 10)):
        queue = await visitor.call("GET", "/queue")
        if check(queue):
            return queue
        await asyncio.sleep(0.1)
    raise TimeoutError("The queue didn't get there in time")
