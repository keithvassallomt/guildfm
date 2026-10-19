import pytest
from fastapi.testclient import TestClient

from guildfm.jingles import Rotation
from guildfm.models import Jingle, JingleKind
from tests.fakes import FakeOpenAI, FakeSpeakers, mp3, spotify_id
from tests.helpers import ADMIN, read_speakers, sign_in

PNG = b"\x89PNG\r\n\x1a\n" + bytes(64)


def songs(**idents: str) -> list[dict]:
    """Twelve picks, with the ident the AI wants before some, by song number: songs(s2="system")."""
    picks = []
    for n in range(1, 13):
        song = {"title": f"Song {n}", "artist": "Fleetwood Mac", "note": f"Note {n}"}
        picks.append(song | {"ident": idents.get(f"s{n}", "none")})
    return picks


@pytest.fixture(autouse=True)
def no_waiting(client: TestClient) -> None:
    """Clips play instantly here."""

    async def nap(seconds: float) -> None:
        pass

    client.app.state.announcer.sleep = nap


def upload(client: TestClient, name: str = "GuildFM", seconds: float = 9.0, **params):
    return client.post(
        "/api/jingles",
        params={"name": name, **params},
        content=mp3(seconds),
        headers={"content-type": "audio/mpeg"},
    )


def make_station(client: TestClient, **fields) -> dict:
    body = {"name": "Guildbert's Hour", "description": "Upbeat soul.", **fields}
    response = client.post("/api/stations", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def put_on(client: TestClient, station: dict) -> None:
    """The station on, its first songs picked, and its first song playing."""
    client.post(f"/api/stations/{station['id']}/play").raise_for_status()
    client.portal.call(client.app.state.radio.settle)
    client.post("/api/playback/play").raise_for_status()


def song_change(client: TestClient, speakers: FakeSpeakers) -> None:
    """The next song is lined up, the current one nears its end, any pause or clips in the
    queue play out, and the next song starts."""
    before = speakers.position
    speakers.track_position = 190
    read_speakers(client)
    client.portal.call(client.app.state.dj.settle)
    client.portal.call(client.app.state.announcer.tick)
    speakers.track_position = 198
    read_speakers(client)
    client.portal.call(client.app.state.announcer.tick)
    if speakers.position == before:  # no pause, so the song plays to the end
        speakers.song_ends()
    read_speakers(client)
    while speakers.on_clip():
        speakers.song_ends()
        read_speakers(client)


def heard(speakers: FakeSpeakers) -> list[str]:
    """The clips that played, in order: from the queue, then any heard in one room."""
    queued = [item.uri for item in speakers.played if item.uri.startswith("http")]
    room = speakers.clips[0].room if speakers.clips else None
    rooms = [clip.url for clip in speakers.clips if clip.room == room]
    return [url.split("/media/", 1)[1] for url in queued + rooms]


def test_admins_look_after_system_idents(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    jingle = upload(client, "GuildFM sting").json()
    assert (jingle["kind"], jingle["name"]) == ("system", "GuildFM sting")
    assert jingle["station_id"] is None
    assert jingle["seconds"] == pytest.approx(9.0, abs=0.1)
    assert jingle["url"].startswith("/media/jingles/")
    assert client.get(jingle["url"]).content == mp3(9.0)
    assert client.get("/api/jingles").json() == [jingle]

    client.delete(f"/api/jingles/{jingle['id']}").raise_for_status()
    assert client.get("/api/jingles").json() == []
    assert client.get(jingle["url"]).status_code == 404


def test_jingles_are_mp3s_of_up_to_a_minute(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    picture = client.post("/api/jingles", params={"name": "Oops"}, content=PNG)
    assert picture.status_code == 415
    assert "isn't an MP3" in picture.json()["detail"]
    long = upload(client, "Too long", seconds=75)
    assert long.status_code == 415
    assert "up to a minute" in long.json()["detail"]
    assert client.get("/api/jingles").json() == []


def test_station_idents_belong_to_their_station(client: TestClient, people) -> None:
    sign_in(client, *people["curator"])
    station = make_station(client)
    jingle = upload(client, "Guildbert", station_id=station["id"]).json()
    assert (jingle["kind"], jingle["station_id"]) == ("station", station["id"])
    assert client.get("/api/jingles", params={"station_id": station["id"]}).json() == [jingle]
    # System idents are for admins.
    assert client.get("/api/jingles").status_code == 403
    assert upload(client).status_code == 403
    # Deleting the station deletes them, files and all.
    client.delete(f"/api/stations/{station['id']}").raise_for_status()
    assert client.get(jingle["url"]).status_code == 404

    sign_in(client, *ADMIN)
    assert client.get("/api/jingles").json() == []
    ai_picks = next(s for s in client.get("/api/stations").json() if s["kind"] == "ai_picks")
    assert upload(client, station_id=ai_picks["id"]).status_code == 409


def test_the_ai_marks_songs_and_the_jingle_plays_before_the_dj(client, openai, speakers) -> None:
    sign_in(client, *ADMIN)
    upload(client, "GuildFM sting")
    station = make_station(client, dj=True, dj_name="Guildbert")
    own = upload(client, "Guildbert", station_id=station["id"]).json()
    openai.picks = songs(s2="station")
    openai.line = {"script": "That was Song 1. Here's Song 2."}
    put_on(client, station)

    asked = openai.asked_for("picks")[0]
    ident = asked["text"]["format"]["schema"]["properties"]["songs"]["items"]["properties"]["ident"]
    assert ident["enum"] == ["none", "system", "station"]
    assert "Idents are short jingles" in asked["input"]
    assert "station, this station's own ident" in asked["input"]

    song_change(client, speakers)
    jingle, line = heard(speakers)
    assert own["url"].endswith(jingle)
    assert line.startswith("speech/")
    # Both from the queue between the songs, then Song 2, and the queue holds just songs again.
    assert speakers.clips == []
    assert (speakers.position, speakers.transport) == (2, "PLAYING")
    assert not any(item.uri.startswith("http") for item in speakers.queue)


def test_never_at_two_song_changes_in_a_row(client, openai, speakers) -> None:
    sign_in(client, *ADMIN)
    upload(client, "GuildFM sting")
    openai.picks = songs(s2="system", s3="system", s4="system")
    put_on(client, make_station(client))
    for _ in range(3):
        song_change(client, speakers)
    # Before Songs 2 and 4, not 3.
    assert len(heard(speakers)) == 2
    assert speakers.position == 4


def test_a_jingle_never_plays_over_music(client, openai, speakers) -> None:
    sign_in(client, *ADMIN)
    upload(client, "GuildFM sting")
    openai.picks = songs(s2="system")
    put_on(client, make_station(client))
    speakers.track_position = 190
    read_speakers(client)
    # Song 2 starts before there's a pause to play it in, so it's let go.
    speakers.song_ends()
    read_speakers(client)
    client.portal.call(client.app.state.announcer.tick)
    assert heard(speakers) == []
    assert not any(item.uri.startswith("http") for item in speakers.queue)


def song_fields(openai: FakeOpenAI) -> dict:
    """What the AI was asked to say about each song, last time it picked."""
    schema = openai.asked_for("picks")[-1]["text"]["format"]["schema"]
    return schema["properties"]["songs"]["items"]["properties"]


def test_no_idents_without_jingles(client, openai: FakeOpenAI, speakers) -> None:
    sign_in(client, *ADMIN)
    openai.picks = songs()
    put_on(client, make_station(client))
    assert "ident" not in song_fields(openai)
    assert "Idents" not in openai.asked_for("picks")[-1]["input"]


def test_no_idents_with_jingles_turned_off(client, openai: FakeOpenAI, speakers) -> None:
    sign_in(client, *ADMIN)
    upload(client, "GuildFM sting")
    openai.picks = songs(s1="system", s2="system")
    put_on(client, make_station(client, jingles=False))
    assert "ident" not in song_fields(openai)
    song_change(client, speakers)
    assert heard(speakers) == []


def test_requests_dont_get_jingles(client, openai, speakers, people) -> None:
    sign_in(client, *ADMIN)
    upload(client, "GuildFM sting")
    openai.picks = songs(s1="system", s2="system")
    put_on(client, make_station(client))
    sign_in(client, *people["user"])
    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()
    song_change(client, speakers)  # the request is next
    assert heard(speakers) == []


def test_the_hour_preview_shows_the_jingles(client: TestClient, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    upload(client, "GuildFM sting", seconds=9.5)
    openai.picks = songs(s2="system")
    body = {"name": "Guildbert's Hour", "description": "Upbeat soul."}
    slots = client.post("/api/stations/preview-hour", json=body).json()["slots"]
    assert [slot["jingle"] and slot["jingle"]["name"] for slot in slots[:3]] == [
        None,
        "GuildFM sting",
        None,
    ]
    # Song 2 starts after Song 1, the jingle and the pause after it.
    assert slots[1]["starts_at"][11:19] == "10:03:30"
    assert slots[2]["starts_at"][11:19] == "10:06:50"


def test_the_same_jingle_never_plays_twice_running() -> None:
    one, two = (
        Jingle(id=n, kind=JingleKind.SYSTEM, name=f"{n}", file="", seconds=9, created_at=0)
        for n in (1, 2)
    )
    rotation = Rotation()
    played = [rotation.next("system", [one, two]) for _ in range(20)]
    assert played[1::2] == [None] * 10  # never two song changes in a row
    chosen = [jingle.id for jingle in played[0::2]]
    assert all(a != b for a, b in zip(chosen, chosen[1:], strict=False))
    # Marked for a kind there's none of: nothing.
    assert Rotation().next("station", [one, two]) is None
