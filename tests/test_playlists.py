import pytest
from fastapi.testclient import TestClient

from guildfm.api.playlists import spotify_link
from guildfm.playlists import best_voted, consider_for_best_voted, tracks_of
from tests.fakes import FakeSpeakers, spotify_id
from tests.helpers import ADMIN, connect_spotify, read_speakers, register, sign_in


def make(client: TestClient, name: str, songs: list[str]) -> dict:
    playlist = client.post("/api/playlists", json={"name": name}).json()
    for song in songs:
        client.post(
            f"/api/playlists/{playlist['id']}/tracks", json={"track_id": spotify_id(song)}
        ).raise_for_status()
    return client.get(f"/api/playlists/{playlist['id']}").json()


def queue(client: TestClient) -> dict:
    return client.get("/api/queue").json()


def playing(client: TestClient) -> str | None:
    entry = queue(client)["playing"]
    return entry and entry["track"]["title"]


def song_ends(client: TestClient, speakers: FakeSpeakers) -> None:
    """Get to the end of the current song: the next is lined up, then the speakers move on."""
    speakers.track_position = 190
    read_speakers(client)
    speakers.song_ends()
    read_speakers(client)


# Making and editing


def test_best_voted_is_always_there_and_first(client: TestClient, people) -> None:
    sign_in(client, *people["curator"])
    make(client, "Aardvark", [])
    lists = client.get("/api/playlists").json()
    assert [p["name"] for p in lists] == ["Best Voted", "Aardvark"]
    assert lists[0]["kind"] == "best_voted"
    assert lists[0]["shuffle"] is True


def test_making_a_playlist(client: TestClient, people) -> None:
    sign_in(client, *people["curator"])
    playlist = make(client, "Friday Afternoon", ["dreams", "gyow"])
    assert playlist["made_by"] == "Curator"
    assert playlist["shuffle"] is False
    # Album art for its tile, each album once.
    assert playlist["covers"] == [
        f"https://i.scdn.co/{spotify_id('dreams')}-300",
        f"https://i.scdn.co/{spotify_id('gyow')}-300",
    ]
    assert [item["title"] for item in playlist["items"]] == ["Dreams", "Go Your Own Way"]

    again = client.post(
        f"/api/playlists/{playlist['id']}/tracks", json={"track_id": spotify_id("dreams")}
    )
    assert again.status_code == 409

    body = client.delete(f"/api/playlists/{playlist['id']}/tracks/{spotify_id('dreams')}").json()
    assert [item["title"] for item in body["items"]] == ["Go Your Own Way"]

    body = client.patch(
        f"/api/playlists/{playlist['id']}", json={"name": "Fridays", "shuffle": True}
    ).json()
    assert (body["name"], body["shuffle"]) == ("Fridays", True)

    assert client.delete(f"/api/playlists/{playlist['id']}").status_code == 204
    assert [p["name"] for p in client.get("/api/playlists").json()] == ["Best Voted"]


def test_best_voted_looks_after_itself(client: TestClient, people) -> None:
    sign_in(client, *people["curator"])
    best = client.get("/api/playlists").json()[0]
    assert client.delete(f"/api/playlists/{best['id']}").status_code == 409
    assert client.patch(f"/api/playlists/{best['id']}", json={"name": "Mine"}).status_code == 409
    add = client.post(f"/api/playlists/{best['id']}/tracks", json={"track_id": spotify_id("fm1")})
    assert add.status_code == 409


@pytest.mark.parametrize(
    ("method", "path"), [("get", "/api/playlists"), ("post", "/api/playlists")]
)
def test_playlists_are_for_curators(client: TestClient, people, method, path) -> None:
    sign_in(client, *people["user"])
    assert client.request(method, path, json={"name": "Mine"}).status_code == 403


# Importing from Spotify


@pytest.mark.parametrize(
    "link",
    [
        f"https://open.spotify.com/playlist/{spotify_id('classics')}?si=abc",
        f"spotify:playlist:{spotify_id('classics')}",
        f"https://open.spotify.com/intl-en/playlist/{spotify_id('classics')}",
    ],
)
def test_playlist_links(link: str) -> None:
    assert spotify_link(link) == ("playlist", spotify_id("classics"))


def test_album_links() -> None:
    album = spotify_id("rumours")
    assert spotify_link(f"https://open.spotify.com/album/{album}?si=x") == ("album", album)
    assert spotify_link(f"spotify:album:{album}") == ("album", album)
    assert spotify_link(f"https://open.spotify.com/track/{album}") is None


def test_importing_a_playlist(client: TestClient) -> None:
    connect_spotify(client)
    link = f"https://open.spotify.com/playlist/{spotify_id('classics')}"
    body = client.post("/api/playlists/import", json={"link": link}).json()
    assert body["name"] == "Office Classics"
    assert body["kind"] == "imported"
    assert [item["title"] for item in body["items"]] == ["Dreams", "Go Your Own Way", "Song 1"]


def test_importing_someone_elses_playlist_explains_why_not(client: TestClient) -> None:
    connect_spotify(client)
    link = f"https://open.spotify.com/playlist/{spotify_id('editorial')}"
    response = client.post("/api/playlists/import", json={"link": link})
    assert response.status_code == 409
    assert "owns or collaborates on" in response.json()["detail"]


def test_importing_problems(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    link = f"https://open.spotify.com/playlist/{spotify_id('classics')}"
    not_connected = client.post("/api/playlists/import", json={"link": link})
    assert not_connected.status_code == 409
    assert "No Spotify account is connected" in not_connected.json()["detail"]

    connect_spotify(client)
    assert client.post("/api/playlists/import", json={"link": "nope"}).status_code == 422
    missing = f"https://open.spotify.com/playlist/{spotify_id('missing')}"
    assert client.post("/api/playlists/import", json={"link": missing}).status_code == 404


# Albums


def titles(playlist: dict) -> list[str]:
    return [item["title"] for item in playlist["items"]]


def test_albums_turn_up_when_adding_to_a_playlist(client: TestClient, people) -> None:
    sign_in(client, *people["curator"])
    found = client.get("/api/search", params={"q": "fleetwood", "albums": "true"}).json()
    assert [album["name"] for album in found["albums"]] == ["Rumours", "Tusk"]
    assert found["albums"][0] == {
        "id": spotify_id("rumours"),
        "name": "Rumours",
        "artists": "Fleetwood Mac",
        "art_url": f"https://i.scdn.co/{spotify_id('rumours')}-300",
        "year": "1977",
        "kind": "album",
        "tracks": 2,
    }
    # Requests are songs only, so the queue's search doesn't ask for albums.
    assert client.get("/api/search", params={"q": "fleetwood"}).json()["albums"] == []


def test_an_albums_songs(client: TestClient, people) -> None:
    sign_in(client, *people["curator"])
    album = client.get(f"/api/albums/{spotify_id('tusk')}").json()
    assert album["name"] == "Tusk"
    # In order, over several pages, leaving out the one that can't play here.
    assert titles(album) == [f"Song {n}" for n in range(1, 21)]
    assert album["items"][0]["album"] == "Tusk"
    assert album["items"][0]["art_url"] == f"https://i.scdn.co/{spotify_id('tusk')}-300"
    missing = client.get(f"/api/albums/{spotify_id('missing')}")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Spotify doesn't have that album."


def test_adding_a_whole_album(client: TestClient, people) -> None:
    sign_in(client, *people["curator"])
    playlist = make(client, "Seventies", ["gyow"])
    path = f"/api/playlists/{playlist['id']}/albums"
    body = client.post(path, json={"album_id": spotify_id("rumours")}).json()
    # A song that was already there stays where it was.
    assert titles(body) == ["Go Your Own Way", "Dreams"]

    again = client.post(path, json={"album_id": spotify_id("rumours")})
    assert again.status_code == 409
    assert again.json()["detail"] == "Every song on that album is already in the playlist."


def test_explicit_album_songs_are_left_out_when_not_allowed(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    assert titles(client.get(f"/api/albums/{spotify_id('damn')}").json()) == ["HUMBLE."]
    client.patch("/api/settings", json={"allow_explicit": False}).raise_for_status()
    assert titles(client.get(f"/api/albums/{spotify_id('damn')}").json()) == []


def test_importing_an_album(client: TestClient) -> None:
    sign_in(client, *ADMIN)  # no Spotify account connected: albums don't need one
    link = f"https://open.spotify.com/album/{spotify_id('rumours')}?si=x"
    body = client.post("/api/playlists/import", json={"link": link}).json()
    assert (body["name"], body["kind"]) == ("Rumours", "imported")
    assert titles(body) == ["Dreams", "Go Your Own Way"]


def test_albums_are_for_curators_and_not_for_best_voted(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    assert client.get(f"/api/albums/{spotify_id('rumours')}").status_code == 403
    sign_in(client, *people["curator"])
    best = client.get("/api/playlists").json()[0]
    added = client.post(
        f"/api/playlists/{best['id']}/albums", json={"album_id": spotify_id("rumours")}
    )
    assert added.status_code == 409


# Playing


def test_a_playlist_fills_the_gaps_between_requests(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    playlist = make(client, "Fridays", ["fm1", "fm2", "fm3", "fm4", "fm5"])
    client.post(f"/api/playlists/{playlist['id']}/play").raise_for_status()
    client.post("/api/playback/play").raise_for_status()

    body = queue(client)
    assert body["playing"]["track"]["title"] == "Song 1"
    assert body["playing"]["playlist"] == "Fridays"
    assert body["playing"]["requested_by"] is None
    assert body["source"]["name"] == "Fridays"
    assert [u["track"]["title"] for u in body["source"]["upcoming"]] == [
        "Song 2",
        "Song 3",
        "Song 4",
    ]

    # A request jumps ahead of the playlist.
    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()
    song_ends(client, speakers)
    assert playing(client) == "Dreams"
    song_ends(client, speakers)
    assert playing(client) == "Song 2"


def test_enough_thumbs_down_skips_a_playlist_song(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    playlist = make(client, "Fridays", ["fm1", "fm2", "fm3"])
    client.post(f"/api/playlists/{playlist['id']}/play").raise_for_status()
    client.post("/api/playback/play").raise_for_status()

    for name in ("dan", "eve", "fay"):
        register(client, name)
        response = client.post(
            "/api/source/vote", json={"track_id": spotify_id("fm2"), "down": True}
        )
    assert response.json() == {"skipped": True}
    upcoming = [u["track"]["title"] for u in queue(client)["source"]["upcoming"]]
    assert upcoming == ["Song 3"]

    sign_in(client, *ADMIN)
    song_ends(client, speakers)
    assert playing(client) == "Song 3"


def test_thumbs_down_are_counted_and_can_be_taken_back(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    playlist = make(client, "Fridays", ["fm1", "fm2"])
    client.post(f"/api/playlists/{playlist['id']}/play").raise_for_status()
    client.post("/api/source/vote", json={"track_id": spotify_id("fm1"), "down": True})
    first = queue(client)["source"]["upcoming"][0]
    assert (first["down"], first["my_down"]) == (1, True)
    client.post("/api/source/vote", json={"track_id": spotify_id("fm1"), "down": False})
    first = queue(client)["source"]["upcoming"][0]
    assert (first["down"], first["my_down"]) == (0, False)


def test_when_the_playlist_runs_out_ai_picks_takes_over(client, speakers, openai) -> None:
    openai.picks = [{"title": "Dreams", "artist": "Fleetwood Mac", "note": "A classic"}]
    sign_in(client, *ADMIN)
    playlist = make(client, "Short", ["fm1", "fm2"])
    client.post(f"/api/playlists/{playlist['id']}/play").raise_for_status()
    client.post("/api/playback/play").raise_for_status()
    song_ends(client, speakers)
    assert playing(client) == "Song 2"
    speakers.track_position = 190
    read_speakers(client)  # Song 2 is the playlist's last: AI picks goes on
    assert queue(client)["source"]["name"] == "AI picks"
    client.portal.call(client.app.state.radio.settle)
    speakers.song_ends()
    read_speakers(client)
    assert playing(client) == "Dreams"


def test_or_starts_over_when_set_to(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    client.patch("/api/settings", json={"queue_runs_out": "restart_playlist"}).raise_for_status()
    playlist = make(client, "Short", ["fm1", "fm2"])
    client.post(f"/api/playlists/{playlist['id']}/play").raise_for_status()
    client.post("/api/playback/play").raise_for_status()
    song_ends(client, speakers)
    song_ends(client, speakers)
    assert playing(client) == "Song 1"


def test_putting_a_playlist_on_starts_it_when_the_music_had_stopped(client, speakers) -> None:
    sign_in(client, *ADMIN)
    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()
    client.post("/api/playback/play").raise_for_status()
    client.post("/api/playback/skip").raise_for_status()
    assert client.get("/api/playback").json()["status"] == "idle"

    playlist = make(client, "Fridays", ["fm1"])
    client.post(f"/api/playlists/{playlist['id']}/play").raise_for_status()
    assert playing(client) == "Song 1"


def test_taking_a_playlist_off(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    playlist = make(client, "Fridays", ["fm1"])
    client.post(f"/api/playlists/{playlist['id']}/play").raise_for_status()
    assert client.get("/api/playlists").json()[1]["playing"] is True
    assert client.delete("/api/source").status_code == 204
    assert queue(client)["source"] is None


def test_an_empty_playlist_cant_be_put_on(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    playlist = make(client, "Nothing", [])
    assert client.post(f"/api/playlists/{playlist['id']}/play").status_code == 409


def test_users_cant_put_playlists_on(client: TestClient, people) -> None:
    sign_in(client, *people["curator"])
    playlist = make(client, "Fridays", ["fm1"])
    sign_in(client, *people["user"])
    assert client.post(f"/api/playlists/{playlist['id']}/play").status_code == 403
    assert client.delete("/api/source").status_code == 403


# Best Voted


def test_well_liked_requests_join_best_voted(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    client.patch("/api/settings", json={"best_voted_min_upvotes": 1}).raise_for_status()
    client.post("/api/queue", json={"track_id": spotify_id("fm1")}).raise_for_status()
    client.post("/api/queue", json={"track_id": spotify_id("fm2")}).raise_for_status()
    entry = queue(client)["waiting"][1]  # Song 2
    for name in ("dan", "eve"):
        register(client, name)
        client.post(f"/api/queue/{entry['id']}/vote", json={"value": 1}).raise_for_status()

    sign_in(client, *ADMIN)
    client.post("/api/playback/play").raise_for_status()  # Song 2 first: it has the votes
    best = client.get("/api/playlists").json()[0]
    items = client.get(f"/api/playlists/{best['id']}").json()["items"]
    assert [(item["title"], item["upvotes"]) for item in items] == [("Song 2", 2)]


async def _evictions(sessionmaker) -> list[tuple[str, int]]:
    async with sessionmaker() as db:
        playlist = await best_voted(db)
        rules = {"more_than": 1, "size": 2}
        await consider_for_best_voted(db, spotify_id("fm1"), 5, **rules)
        await consider_for_best_voted(db, spotify_id("fm2"), 3, **rules)
        # Full: a newcomer with fewer upvotes than the weakest stays out...
        await consider_for_best_voted(db, spotify_id("fm3"), 2, **rules)
        # ...one with as many replaces it...
        await consider_for_best_voted(db, spotify_id("fm4"), 3, **rules)
        # ...and one already there just keeps its best count.
        await consider_for_best_voted(db, spotify_id("fm1"), 4, **rules)
        return [(e.track_id, e.upvotes) for e in await tracks_of(db, playlist.id)]


def test_best_voted_keeps_the_best_when_full(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    client.get("/api/search", params={"q": "song"})  # gets the songs into the local catalogue
    client.get("/api/search", params={"q": "song", "offset": 20})
    entries = client.portal.call(_evictions, client.app.state.sessionmaker)
    assert entries == [(spotify_id("fm1"), 5), (spotify_id("fm4"), 3)]
