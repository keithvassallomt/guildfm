import pytest
from fastapi.testclient import TestClient

from guildfm.live import LiveHub
from guildfm.playback import NothingToPlay, NotInControl, PlaybackController, Status
from guildfm.speakers import SpeakersRefused, spotify_item
from tests.fakes import FakeSpeakers, spotify_id
from tests.helpers import ADMIN, read_speakers, sign_in

TRACK = spotify_item("6SP5GXlyb0yiCCMODUjeFb", sid=9, sn=1)
OTHER = spotify_item("1sYRkVKdT2ize1HSDCwbEF", sid=9, sn=1)


class Steady:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def steady() -> Steady:
    return Steady()


@pytest.fixture
def controller(speakers: FakeSpeakers, steady: Steady) -> PlaybackController:
    return PlaybackController(speakers, LiveHub(), clock=steady)


async def outside_takeover(controller, speakers, steady) -> None:
    steady.advance(5)
    speakers.someone_plays_radio()
    await controller.poll()
    await controller.poll()


# The controller


async def test_starts_stopped_and_leaves_other_music_alone(controller, speakers) -> None:
    await controller.poll(full=True)
    assert controller.status == Status.STOPPED
    assert controller.state()["track"]["title"] == "Nobody's Business"
    assert len(controller.state()["rooms"]) == 3
    assert speakers.took_over == []


async def test_nothing_to_play_until_something_is_queued(controller) -> None:
    await controller.poll()
    with pytest.raises(NothingToPlay):
        await controller.play()


async def test_play_now_takes_the_speakers_over(controller, speakers) -> None:
    await controller.play_now(TRACK)
    assert speakers.took_over == [[TRACK]]
    assert controller.status == Status.PLAYING
    assert controller.state()["track"]["ours"] is True


async def test_next_track_plays_without_another_takeover(controller, speakers) -> None:
    await controller.play_now(TRACK)
    await controller.play_now(OTHER)
    assert len(speakers.took_over) == 1
    assert speakers.queue == [TRACK, OTHER]
    assert speakers.position == 2


async def test_outside_takeover_is_noticed_after_settling(controller, speakers, steady) -> None:
    await controller.play_now(TRACK)
    speakers.someone_plays_radio()
    await controller.poll()
    await controller.poll()
    assert controller.status == Status.PLAYING  # GuildFM's own command is still settling
    steady.advance(5)
    await controller.poll()
    assert controller.status == Status.PLAYING  # one odd reading isn't enough
    await controller.poll()
    assert controller.status == Status.OVERRIDDEN
    with pytest.raises(NotInControl):
        await controller.skip()


async def test_play_takes_back_control_where_it_left_off(controller, speakers, steady) -> None:
    await controller.play_now(TRACK)
    await controller.play_now(OTHER)
    await outside_takeover(controller, speakers, steady)
    assert controller.status == Status.OVERRIDDEN

    await controller.play()
    assert speakers.took_over[-1] == [OTHER]
    assert controller.status == Status.PLAYING


async def test_pausing_from_the_sonos_app_isnt_a_takeover(controller, speakers, steady) -> None:
    await controller.play_now(TRACK)
    steady.advance(5)
    speakers.someone_pauses()
    await controller.poll()
    await controller.poll()
    assert controller.status == Status.PAUSED

    await controller.play()
    assert controller.status == Status.PLAYING
    assert len(speakers.took_over) == 1  # resumed, not taken over again


async def test_stop_silences_the_speakers_and_stops_watching(controller, speakers, steady) -> None:
    await controller.play_now(TRACK)
    await controller.stop()
    assert speakers.transport == "PAUSED_PLAYBACK"
    assert controller.status == Status.STOPPED

    await outside_takeover(controller, speakers, steady)
    assert controller.status == Status.STOPPED  # GuildFM had already stepped back

    await controller.play()
    assert speakers.took_over[-1] == [TRACK]
    assert controller.status == Status.PLAYING


async def test_stop_then_play_resumes_without_a_takeover(controller, speakers) -> None:
    await controller.play_now(TRACK)
    await controller.stop()
    await controller.play()
    assert len(speakers.took_over) == 1
    assert speakers.transport == "PLAYING"


async def test_queue_running_out_is_idle(controller) -> None:
    await controller.play_now(TRACK)
    await controller.skip()
    assert controller.status == Status.IDLE


async def test_speakers_going_away_and_coming_back(controller, speakers) -> None:
    await controller.play_now(TRACK)
    speakers.available = False
    await controller.poll()
    assert controller.status == Status.OFFLINE
    assert "No Sonos speakers" in controller.state()["error"]

    speakers.available = True
    await controller.poll()
    assert controller.status == Status.PLAYING


async def test_tv_takes_only_the_arc_out_of_the_group(controller, speakers, steady) -> None:
    await controller.play_now(TRACK)
    steady.advance(5)
    speakers.tv_turns_on()
    await controller.poll(full=True)
    await controller.poll(full=True)
    arc = next(room for room in controller.state()["rooms"] if room["name"] == "Downstairs")
    assert arc["on_tv"] is True
    assert arc["in_group"] is False
    assert controller.status == Status.PLAYING


async def test_track_changes_are_reported(controller) -> None:
    changes = []

    async def record(before, after) -> None:
        changes.append((before, after))

    controller.on_track_change.append(record)
    await controller.poll()
    await controller.play_now(TRACK)
    assert changes[-1] == ("x-sonos-http:sonos%3aradio-track", TRACK.uri)


async def test_volumes(controller) -> None:
    await controller.set_room_volume("RINCON_KITCHEN", 30)
    rooms = {room["uid"]: room for room in controller.state()["rooms"]}
    assert rooms["RINCON_KITCHEN"]["volume"] == 30

    await controller.set_group_volume(10)
    assert controller.state()["group_volume"] == 10


# The API


def request(client: TestClient, name: str) -> None:
    client.post("/api/queue", json={"track_id": spotify_id(name)}).raise_for_status()


def test_everyone_signed_in_can_see_whats_playing(client: TestClient, people) -> None:
    assert client.get("/api/playback").status_code == 401
    sign_in(client, *people["user"])
    read_speakers(client)
    state = client.get("/api/playback").json()
    assert state["status"] == "stopped"
    assert state["track"]["title"] == "Nobody's Business"


COMMANDS = [
    ("post", "/api/playback/play", None),
    ("post", "/api/playback/pause", None),
    ("post", "/api/playback/skip", None),
    ("post", "/api/playback/stop", None),
    ("put", "/api/playback/volume", {"volume": 10}),
    ("put", "/api/playback/rooms/RINCON_KITCHEN/volume", {"volume": 10}),
]


@pytest.mark.parametrize(("method", "path", "body"), COMMANDS)
@pytest.mark.parametrize("who", ["user", "curator"])
def test_only_admins_control_playback(client: TestClient, people, method, path, body, who):
    sign_in(client, *people[who])
    assert client.request(method, path, json=body).status_code == 403


def test_admin_plays_pauses_and_stops(client: TestClient, speakers: FakeSpeakers) -> None:
    sign_in(client, *ADMIN)
    request(client, "dreams")
    state = client.post("/api/playback/play").json()
    assert state["status"] == "playing"
    assert spotify_id("dreams") in speakers.took_over[0][0].uri

    assert client.post("/api/playback/pause").json()["status"] == "paused"
    assert client.post("/api/playback/stop").json()["status"] == "stopped"


def test_playback_problems_read_well(client: TestClient, speakers: FakeSpeakers) -> None:
    sign_in(client, *ADMIN)
    assert client.post("/api/playback/play").json()["detail"] == "There's nothing to play yet."
    assert client.post("/api/playback/skip").status_code == 409

    speakers.available = False
    response = client.put("/api/playback/volume", json={"volume": 10})
    assert response.status_code == 503
    assert "No Sonos speakers" in response.json()["detail"]


def test_skipping_the_last_song_ends_playback(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    request(client, "dreams")
    client.post("/api/playback/play").raise_for_status()
    response = client.post("/api/playback/skip")
    assert response.status_code == 200
    assert response.json()["status"] == "idle"


def test_a_refusal_from_the_speakers_isnt_an_outage(client: TestClient, speakers, monkeypatch):
    sign_in(client, *ADMIN)
    request(client, "dreams")
    client.post("/api/playback/play").raise_for_status()

    def refuse() -> None:
        raise SpeakersRefused("The speakers wouldn't do that (Illegal seek target).")

    monkeypatch.setattr(speakers, "skip", refuse)
    response = client.post("/api/playback/skip")
    assert response.status_code == 409
    assert "Illegal seek target" in response.json()["detail"]
    assert client.get("/api/playback").json()["status"] == "playing"
