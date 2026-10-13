from guildfm.speakers import QUEUE_URI, QueueItem, Room, Snapshot, SpeakersUnavailable, Track

COORDINATOR = "RINCON_LOUNGE"
RADIO = "x-sonosapi-radio:sonos%3a3094?sid=303&flags=8232&sn=8"


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
            track = item and Track(item.uri, "Queued track", "", "", None, 200, 3)
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
            self.position += 1
        else:
            self.transport = "STOPPED"

    def set_group_volume(self, volume: int) -> None:
        self._check()
        for uid, room in self.rooms.items():
            self.rooms[uid] = Room(
                room.uid, room.name, room.model, volume, room.in_group, room.on_tv
            )

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

    def play_position(self, position: int) -> None:
        self._check()
        self.position = position
        self.transport = "PLAYING"

    def own_address(self) -> str:
        return "127.0.0.1"
