from fastapi.testclient import TestClient

from guildfm.live import LiveHub
from guildfm.monitor import MonitorRelay, MonitorSystem
from guildfm.speakers import clip_item, spotify_item
from tests.conftest import Ticker
from tests.fakes import FakeSpeakers, spotify_id
from tests.helpers import ADMIN, read_speakers, sign_in

SONG = spotify_item(spotify_id("fm1"), sid=9, sn=1, seconds=200)
OTHER = spotify_item(spotify_id("fm2"), sid=9, sn=1, seconds=100)
LINE = clip_item("http://127.0.0.1:8000/media/speech/line.mp3", "Della", seconds=8)


# The stand-in for the speakers


def test_songs_last_as_long_as_the_real_ones(ticker: Ticker) -> None:
    monitor = MonitorSystem(clock=ticker)
    assert monitor.snapshot(True).track is None  # nothing until GuildFM takes over
    monitor.take_over([SONG, OTHER])
    ticker.now += 150
    playing = monitor.snapshot(False)
    assert (playing.queue_position, playing.track.position) == (1, 150)
    ticker.now += 60
    playing = monitor.snapshot(False)
    assert (playing.queue_position, playing.track.position) == (2, 10)
    ticker.now += 100
    assert monitor.snapshot(False).transport == "STOPPED"  # the queue ran out


def test_pausing_keeps_the_place(ticker: Ticker) -> None:
    monitor = MonitorSystem(clock=ticker)
    monitor.take_over([SONG])
    ticker.now += 30
    monitor.pause()
    ticker.now += 500
    assert monitor.snapshot(False).track.position == 30
    monitor.play()
    ticker.now += 5
    assert monitor.snapshot(False).track.position == 35


def test_a_clip_in_the_queue_plays_between_the_songs(ticker: Ticker) -> None:
    monitor = MonitorSystem(clock=ticker)
    monitor.take_over([SONG, OTHER])
    assert monitor.add_at(LINE, 2) == 2
    ticker.now += 203
    playing = monitor.snapshot(False)
    assert (playing.track.uri, playing.track.title, playing.track.position) == (
        LINE.uri,
        "Della",
        3,
    )
    item = monitor.state()["item"]
    assert (item["kind"], item["path"]) == ("clip", "/media/speech/line.mp3")
    ticker.now += 5
    assert monitor.snapshot(False).track.uri == OTHER.uri


def test_clips_over_the_music_reach_browsers_by_path(ticker: Ticker) -> None:
    monitor = MonitorSystem(clock=ticker)
    monitor.take_over([SONG])
    monitor.play_clip("GUILDFM_MONITOR", "http://10.0.0.5:8000/media/speech/hello.mp3", 25)
    ticker.now += 2
    state = monitor.state()
    assert state["item"]["kind"] == "song"
    assert state["overlays"] == [
        {"id": 1, "path": "/media/speech/hello.mp3", "volume": 25, "age": 2.0}
    ]
    ticker.now += 60
    monitor.tick()
    assert monitor.state()["overlays"] == []  # long gone


class Hub(LiveHub):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[tuple[str, dict]] = []

    async def broadcast(self, event, data=None) -> None:
        self.sent.append((event, data))


async def test_the_relay_sends_changes_only_while_monitor_mode_is_on(ticker: Ticker) -> None:
    monitor, hub, on = MonitorSystem(clock=ticker), Hub(), [False]
    relay = MonitorRelay(monitor, hub, lambda: on[0])
    await relay.tick()
    assert hub.sent == []
    on[0] = True
    await relay.tick()
    await relay.tick()  # nothing changed
    monitor.take_over([SONG])
    await relay.tick()
    assert [event for event, _ in hub.sent] == ["monitor", "monitor"]
    assert hub.sent[-1][1]["transport"] == "PLAYING"


# Turning it on and off


def request(client: TestClient, name: str) -> None:
    client.post("/api/queue", json={"track_id": spotify_id(name)}).raise_for_status()


def playing_on_the_speakers(client: TestClient, speakers: FakeSpeakers) -> None:
    sign_in(client, *ADMIN)
    request(client, "fm1")
    request(client, "fm2")
    client.post("/api/playback/play").raise_for_status()
    read_speakers(client)


def monitor_mode(client: TestClient, on: bool) -> dict:
    response = client.put("/api/playback/monitor", json={"on": on})
    response.raise_for_status()
    return response.json()


def test_turning_it_on_stops_the_speakers_and_plays_in_browsers(client, speakers) -> None:
    playing_on_the_speakers(client, speakers)
    state = monitor_mode(client, True)
    assert speakers.transport == "PAUSED_PLAYBACK"
    assert (state["monitor"], state["status"], state["coordinator"]) == (True, "stopped", "Monitor")
    assert client.get("/api/settings").json()["values"]["monitor"] is True

    client.post("/api/playback/play").raise_for_status()
    assert client.get("/api/playback").json()["status"] == "playing"
    assert client.get("/api/playback/monitor").json()["item"]["kind"] == "song"
    assert len(speakers.took_over) == 1  # the speakers only had the first time
    assert client.get("/api/queue").json()["playing"]["track"]["title"] == "Song 1"
    services = client.get("/api/status").json()["services"]
    assert next(s for s in services if s["key"] == "speakers")["state"] == "off"


def test_turning_it_off_goes_back_to_the_speakers(client, speakers, monitor) -> None:
    playing_on_the_speakers(client, speakers)
    monitor_mode(client, True)
    client.post("/api/playback/play").raise_for_status()
    state = monitor_mode(client, False)
    assert (state["monitor"], state["status"]) == (False, "stopped")
    assert monitor.snapshot(False).transport == "PAUSED_PLAYBACK"

    client.post("/api/playback/play").raise_for_status()
    assert len(speakers.took_over) == 2  # taken over afresh, from Song 1
    assert (
        speakers.queue[speakers.position - 1].key
        == spotify_item(spotify_id("fm1"), sid=9, sn=1).key
    )


def test_only_admins_switch_it(client, people) -> None:
    sign_in(client, *people["curator"])
    response = client.put("/api/playback/monitor", json={"on": True})
    assert response.status_code == 403


def test_it_stays_on_after_a_restart(start, speakers) -> None:
    with start() as client:
        playing_on_the_speakers(client, speakers)
        monitor_mode(client, True)
    with start() as client:
        sign_in(client, *ADMIN)
        state = client.get("/api/playback").json()
        assert (state["monitor"], state["status"]) == (True, "stopped")


def test_announcements_for_chosen_rooms_play_in_the_browser(client, speakers, monitor) -> None:
    playing_on_the_speakers(client, speakers)
    monitor_mode(client, True)
    client.post("/api/playback/play").raise_for_status()

    async def nap(seconds: float) -> None:
        pass

    client.app.state.announcer.sleep = nap
    kitchen = {"uid": "RINCON_KITCHEN", "name": "Kitchen"}
    client.post(
        "/api/announcements/now", json={"text": "Lunch!", "mode": "over", "rooms": [kitchen]}
    ).raise_for_status()
    client.portal.call(client.app.state.announcer.tick)
    overlays = monitor.state()["overlays"]
    assert len(overlays) == 1 and overlays[0]["path"].startswith("/media/speech/")
    assert speakers.clips == []
