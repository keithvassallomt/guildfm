"""The office Sonos system, driven over the local network with SoCo.

Everything here is synchronous and talks to the speakers directly; the playback controller runs
it in a worker thread, one call at a time.
"""

import contextlib
import json
import socket
import ssl
import threading
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol
from xml.sax.saxutils import escape

import soco
from soco import SoCo
from soco.exceptions import SoCoUPnPException
from websockets.sync.client import connect

QUEUE_URI = "x-rincon-queue:{uid}#0"

# Overlay clips go over each speaker's local websocket, with the key the Sonos app itself uses.
CLIP_PORT = 1443
CLIP_PROTOCOL = "v1.api.smartspeaker.audio"
CLIP_API_KEY = "123e4567-e89b-12d3-a456-426655440000"
CLIP_TIMEOUT = 5


class SpeakersUnavailable(Exception):
    """The speakers can't be found or aren't answering."""


class SpeakersRefused(Exception):
    """The speakers answered, but turned the command down."""


@dataclass(frozen=True)
class Room:
    uid: str
    name: str
    model: str
    volume: int
    in_group: bool
    on_tv: bool


@dataclass(frozen=True)
class Track:
    uri: str
    title: str
    artist: str
    album: str
    art_url: str | None
    duration: int
    position: int


@dataclass(frozen=True)
class Snapshot:
    coordinator_uid: str
    coordinator_name: str
    transport: str  # PLAYING, PAUSED_PLAYBACK, STOPPED or TRANSITIONING
    media_uri: str
    track: Track | None
    queue_position: int | None  # 1-based position in the Sonos queue
    group_volume: int
    rooms: list[Room] = field(default_factory=list)  # only filled in by a full snapshot

    @property
    def playing_our_queue(self) -> bool:
        return self.media_uri == QUEUE_URI.format(uid=self.coordinator_uid)


@dataclass(frozen=True)
class QueueItem:
    """Something to put in the Sonos queue: a Spotify track or an MP3 that GuildFM serves."""

    uri: str
    metadata: str
    # How long it lasts, when GuildFM knows. Only monitor mode needs it: the speakers find out
    # for themselves.
    seconds: float | None = field(default=None, compare=False)

    @property
    def key(self) -> str:
        return track_key(self.uri)


def track_key(uri: str) -> str:
    """The part of a track URI that identifies it; the speakers add account details after `?`."""
    return uri.split("?", 1)[0]


def spotify_track_id(uri: str | None) -> str | None:
    """The Spotify track id in a Sonos track URI, if it's a Spotify track."""
    if not uri:
        return None
    _, found, rest = track_key(uri).partition("spotify%3atrack%3a")
    return rest or None if found else None


_DIDL = (
    '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
    'xmlns:r="urn:schemas-rinconnetworks-com:metadata-1-0/" '
    'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">{item}</DIDL-Lite>'
)


def spotify_item(track_id: str, *, sid: int, sn: int, seconds: float | None = None) -> QueueItem:
    """A Spotify track, played by the speakers through the Spotify account linked in Sonos."""
    encoded = f"spotify%3atrack%3a{track_id}"
    service = sid * 256 + 7
    item = (
        f'<item id="00032020{encoded}" parentID="" restricted="true">'
        "<dc:title></dc:title><upnp:class>object.item.audioItem.musicTrack</upnp:class>"
        '<desc id="cdudn" nameSpace="urn:schemas-rinconnetworks-com:metadata-1-0/">'
        f"SA_RINCON{service}_X_#Svc{service}-0-Token</desc></item>"
    )
    uri = f"x-sonos-spotify:{encoded}?sid={sid}&flags=8232&sn={sn}"
    return QueueItem(uri=uri, metadata=_DIDL.format(item=item), seconds=seconds)


def clip_item(
    url: str, title: str, artist: str = "GuildFM", seconds: float | None = None
) -> QueueItem:
    """An MP3 that the speakers fetch from GuildFM, such as the DJ between songs. The title and
    artist are what the Sonos app shows while it plays."""
    item = (
        '<item id="guildfm-clip" parentID="" restricted="true">'
        f"<dc:title>{escape(title)}</dc:title><dc:creator>{escape(artist)}</dc:creator>"
        "<upnp:class>object.item.audioItem.musicTrack</upnp:class>"
        f'<res protocolInfo="http-get:*:audio/mpeg:*">{escape(url)}</res></item>'
    )
    return QueueItem(uri=url, metadata=_DIDL.format(item=item), seconds=seconds)


class SpeakerSystem(Protocol):
    def snapshot(self, full: bool) -> Snapshot: ...
    def play(self) -> None: ...
    def pause(self) -> None: ...
    def skip(self) -> None: ...
    def set_group_volume(self, volume: int) -> None: ...
    def set_room_volume(self, uid: str, volume: int) -> None: ...
    def take_over(self, items: list[QueueItem]) -> None: ...
    def add_next(self, item: QueueItem) -> int: ...
    def add_at(self, item: QueueItem, position: int) -> int: ...
    def remove(self, position: int) -> None: ...
    def play_position(self, position: int) -> None: ...
    def play_clip(
        self, uid: str, url: str, volume: int, start: threading.Barrier | None = None
    ) -> None: ...
    def own_address(self) -> str: ...


def _seconds(clock: str | None) -> int:
    """'0:03:28' to 208. Radio streams report blanks or 'NOT_IMPLEMENTED'."""
    try:
        hours, minutes, seconds = (int(part) for part in (clock or "").split(":"))
    except ValueError:
        return 0
    return hours * 3600 + minutes * 60 + seconds


class SocoSystem:
    """The real speakers. `hosts` skips discovery and talks to those addresses directly."""

    def __init__(self, hosts: list[str]) -> None:
        self._hosts = hosts
        self._zones: list[SoCo] = []
        self._coordinator: SoCo | None = None
        self._models: dict[str, str] = {}
        self._households: dict[str, str] = {}

    def _find(self) -> None:
        zones = [SoCo(host) for host in self._hosts] if self._hosts else soco.discover(timeout=3)
        if not zones:
            raise SpeakersUnavailable("No Sonos speakers found on the network.")
        self._zones = sorted(zones, key=lambda zone: zone.player_name)
        # GuildFM plays to the biggest group, which is normally every room.
        groups = self._zones[0].all_groups
        self._coordinator = max(groups, key=lambda group: len(group.members)).coordinator

    def _guard(self, action):
        try:
            if self._coordinator is None:
                self._find()
            return action()
        except SpeakersUnavailable:
            raise
        except SoCoUPnPException as error:
            # The speakers answered, so the connection is fine; they just wouldn't do it.
            reason = error.error_description or error.error_code
            raise SpeakersRefused(f"The speakers wouldn't do that ({reason}).") from error
        except Exception as error:
            # Forget everything and look the speakers up again next time.
            self._zones, self._coordinator = [], None
            raise SpeakersUnavailable(f"The speakers aren't answering: {error}") from error

    def _model(self, zone: SoCo) -> str:
        if zone.uid not in self._models:
            self._models[zone.uid] = zone.get_speaker_info().get("model_name", "Sonos")
        return self._models[zone.uid]

    def snapshot(self, full: bool) -> Snapshot:
        def read() -> Snapshot:
            if full:
                self._find()
            coordinator = self._coordinator
            transport = coordinator.get_current_transport_info()["current_transport_state"]
            media = coordinator.get_current_media_info()
            info = coordinator.get_current_track_info()
            track = None
            if info.get("uri"):
                track = Track(
                    uri=info["uri"],
                    title=info.get("title") or "",
                    artist=info.get("artist") or "",
                    album=info.get("album") or "",
                    art_url=info.get("album_art") or None,
                    duration=_seconds(info.get("duration")),
                    position=_seconds(info.get("position")),
                )
            position = info.get("playlist_position")
            rooms = []
            if full:
                members = {zone.uid for zone in coordinator.group.members}
                rooms = [
                    Room(
                        uid=zone.uid,
                        name=zone.player_name,
                        model=self._model(zone),
                        volume=zone.volume,
                        in_group=zone.uid in members,
                        on_tv=zone.is_playing_tv,
                    )
                    for zone in self._zones
                ]
            return Snapshot(
                coordinator_uid=coordinator.uid,
                coordinator_name=coordinator.player_name,
                transport=transport,
                media_uri=media.get("uri") or "",
                track=track,
                queue_position=int(position) if position and position.isdigit() else None,
                group_volume=coordinator.group.volume,
                rooms=rooms,
            )

        return self._guard(read)

    def play(self) -> None:
        self._guard(lambda: self._coordinator.play())

    def pause(self) -> None:
        self._guard(lambda: self._coordinator.pause())

    def skip(self) -> None:
        def apply() -> None:
            coordinator = self._coordinator
            current = coordinator.get_current_track_info().get("playlist_position") or "0"
            # Sonos refuses "next" on the last track, so skipping that one just ends playback.
            if current.isdigit() and int(current) >= coordinator.queue_size:
                coordinator.stop()
            else:
                coordinator.next()

        self._guard(apply)

    def set_group_volume(self, volume: int) -> None:
        def apply() -> None:
            self._coordinator.group.volume = volume

        self._guard(apply)

    def set_room_volume(self, uid: str, volume: int) -> None:
        def apply() -> None:
            zone = next((zone for zone in self._zones if zone.uid == uid), None)
            if zone is None:
                raise SpeakersUnavailable("That room isn't on the network any more.")
            zone.volume = volume

        self._guard(apply)

    def _enqueue(self, item: QueueItem, position: int) -> int:
        response = self._coordinator.avTransport.AddURIToQueue(
            [
                ("InstanceID", 0),
                ("EnqueuedURI", item.uri),
                ("EnqueuedURIMetaData", item.metadata),
                ("DesiredFirstTrackNumberEnqueued", position),
                ("EnqueueAsNext", 0),
            ]
        )
        return int(response["FirstTrackNumberEnqueued"])

    def take_over(self, items: list[QueueItem]) -> None:
        """Bring every room that isn't on the TV into one group, and play `items` from the top."""

        def apply() -> None:
            self._find()
            coordinator = self._coordinator
            for zone in self._zones:
                elsewhere = zone.group.coordinator.uid != coordinator.uid
                if elsewhere and not zone.is_playing_tv:
                    zone.join(coordinator)
            coordinator.clear_queue()
            for item in items:
                self._enqueue(item, 0)
            coordinator.play_from_queue(0)

        self._guard(apply)

    def add_next(self, item: QueueItem) -> int:
        def apply() -> int:
            info = self._coordinator.get_current_track_info()
            current = info.get("playlist_position") or "0"
            return self._enqueue(item, int(current) + 1 if current.isdigit() else 0)

        return self._guard(apply)

    def add_at(self, item: QueueItem, position: int) -> int:
        """Put `item` in the queue at `position`, moving what was there down one."""
        return self._guard(lambda: self._enqueue(item, position))

    def remove(self, position: int) -> None:
        self._guard(lambda: self._coordinator.remove_from_queue(position - 1))

    def play_position(self, position: int) -> None:
        self._guard(lambda: self._coordinator.play_from_queue(position - 1))

    def play_clip(
        self, uid: str, url: str, volume: int, start: threading.Barrier | None = None
    ) -> None:
        """Play the MP3 at `url` in one room, over whatever it's playing: the music goes quiet
        and comes back up afterwards. Each room takes its own call. Safe to run alongside other
        speaker calls, so it doesn't go through `_guard`.

        Rooms playing the same clip share `start`: each connects, then waits there until they
        all have, and they send together. Connecting takes some speakers a tenth of a second
        longer than others, which within earshot of each other sounds like an echo."""
        zone = next((zone for zone in self._zones if zone.uid == uid), None)
        if zone is None:
            if start:
                start.abort()
            raise SpeakersUnavailable("That room isn't on the network any more.")
        name = "A speaker"
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE  # each speaker signs its own certificate
        try:
            name = zone.player_name
            if uid not in self._households:
                info = f"http://{zone.ip_address}:1400/info"
                with urllib.request.urlopen(info, timeout=CLIP_TIMEOUT) as response:
                    self._households[uid] = json.load(response)["householdId"]
            with connect(
                f"wss://{zone.ip_address}:{CLIP_PORT}/websocket/api",
                ssl=context,
                subprotocols=[CLIP_PROTOCOL],
                additional_headers={"X-Sonos-Api-Key": CLIP_API_KEY},
                open_timeout=CLIP_TIMEOUT,
            ) as websocket:
                # If a room couldn't connect, or took too long, the rest go without it.
                if start:
                    with contextlib.suppress(threading.BrokenBarrierError):
                        start.wait(CLIP_TIMEOUT)
                command = {
                    "namespace": "audioClip:1",
                    "command": "loadAudioClip",
                    "playerId": uid,
                    "householdId": self._households[uid],
                }
                clip = {
                    "name": "GuildFM",
                    "appId": "com.guildfm",
                    "streamUrl": url,
                    "volume": volume,
                }
                websocket.send(json.dumps([command, clip]))
                reply = json.loads(websocket.recv(timeout=CLIP_TIMEOUT))
        except Exception as error:  # SoCo, the network, the websocket or a garbled reply
            if start:
                start.abort()  # so the rooms waiting for this one go ahead
            raise SpeakersUnavailable(f"{name} isn't answering: {error}") from error
        headers, body = (reply + [{}])[:2] if isinstance(reply, list) else (reply, {})
        if headers.get("success") is False or body.get("_objectType") == "globalError":
            reason = body.get("errorCode") or body.get("reason") or "no reason given"
            raise SpeakersRefused(f"{name} wouldn't play it ({reason}).")

    def own_address(self) -> str:
        """This machine's address on the speakers' network, for links the speakers fetch."""

        def find() -> str:
            # Connecting a UDP socket sends nothing; it just picks the route to the speakers.
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect((self._coordinator.ip_address, 1400))
                return probe.getsockname()[0]

        return self._guard(find)
