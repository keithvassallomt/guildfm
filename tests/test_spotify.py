import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from guildfm.config import Settings
from tests.fakes import FakeSpotify, spotify_id
from tests.helpers import ADMIN, sign_in

# Searching


def test_search_finds_tracks_with_artwork(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    result = client.get("/api/search", params={"q": "dreams"}).json()
    assert result["tracks"] == [
        {
            "id": spotify_id("dreams"),
            "title": "Dreams",
            "artists": "Fleetwood Mac",
            "album": "Rumours",
            "duration": 200,
            "explicit": False,
            "art_url": f"https://i.scdn.co/{spotify_id('dreams')}-300",
            "queued": False,
            "played_at": None,
        }
    ]
    assert [artist["name"] for artist in result["artists"]] == ["Fleetwood Mac"]


def test_search_pages_past_spotifys_limit_of_ten(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    first = client.get("/api/search", params={"q": "fleetwood"}).json()
    assert len(first["tracks"]) == 20
    assert first["next_offset"] == 20

    second = client.get("/api/search", params={"q": "fleetwood", "offset": 20}).json()
    assert len(second["tracks"]) == 2  # three more, one of which can't play here
    assert second["next_offset"] is None
    assert second["artists"] == []
    ids = [t["id"] for t in first["tracks"] + second["tracks"]]
    assert len(set(ids)) == 22


def test_search_leaves_out_tracks_spotify_repeats(client: TestClient, people, spotify) -> None:
    spotify.overlap = 2
    sign_in(client, *people["user"])
    tracks = client.get("/api/search", params={"q": "fleetwood"}).json()["tracks"]
    ids = [t["id"] for t in tracks]
    assert len(ids) == 18
    assert len(set(ids)) == 18


def test_search_by_artist(client: TestClient, people) -> None:
    sign_in(client, *ADMIN)
    client.patch("/api/settings", json={"allow_explicit": True}).raise_for_status()
    sign_in(client, *people["user"])
    result = client.get("/api/search", params={"artist": "Kendrick Lamar"}).json()
    assert [t["title"] for t in result["tracks"]] == ["HUMBLE."]
    assert result["artists"] == []


def test_found_tracks_are_kept_locally(client: TestClient, people, settings: Settings) -> None:
    sign_in(client, *people["user"])
    client.get("/api/search", params={"q": "humble"}).raise_for_status()
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        row = db.execute("SELECT title, artists, explicit, art_url FROM tracks").fetchone()
    assert row == ("HUMBLE.", "Kendrick Lamar", 1, f"https://i.scdn.co/{spotify_id('humble')}-300")


def test_explicit_tracks_hidden_unless_allowed(client: TestClient, people, settings):
    sign_in(client, *people["user"])
    assert client.get("/api/search", params={"q": "humble"}).json()["tracks"] == []
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        db.execute("INSERT INTO settings (key, value) VALUES ('allow_explicit', 'true')")
    assert client.get("/api/search", params={"q": "humble"}).json()["tracks"]


def test_search_needs_signing_in_and_something_to_find(client: TestClient, people) -> None:
    assert client.get("/api/search", params={"q": "dreams"}).status_code == 401
    sign_in(client, *people["user"])
    assert client.get("/api/search", params={"q": "  "}).status_code == 422


def test_the_app_token_is_reused(client: TestClient, people, spotify: FakeSpotify) -> None:
    sign_in(client, *people["user"])
    for query in ("dreams", "humble", "fleetwood"):
        client.get("/api/search", params={"q": query}).raise_for_status()
    assert spotify.token_requests == ["client_credentials"]


def test_spotify_being_busy_reads_well(client: TestClient, people, spotify: FakeSpotify) -> None:
    sign_in(client, *people["user"])
    spotify.busy = True
    response = client.get("/api/search", params={"q": "dreams"})
    assert response.status_code == 503
    assert response.json()["detail"] == "Spotify is busy. Try again in 7 seconds."


# Connecting an account for playlist import


def connect(client: TestClient) -> str:
    """Go through Spotify's sign-in as an admin, returning the page Spotify sends people back to."""
    sign_in(client, *ADMIN)
    url = client.post("/api/spotify/connect").json()["url"]
    query = parse_qs(urlparse(url).query)
    assert query["redirect_uri"] == ["http://127.0.0.1:8000/auth/spotify/callback"]
    assert query["scope"] == ["playlist-read-private playlist-read-collaborative"]
    state = query["state"][0]
    return client.get("/auth/spotify/callback", params={"code": "abc", "state": state}).text


def test_connecting_an_account(client: TestClient) -> None:
    assert "Spotify connected" in connect(client)
    account = client.get("/api/spotify/account").json()
    assert account["connected"] is True
    assert account["display_name"] == "Office Spotify"
    assert account["playlists"] == 7
    assert account["reconnect_soon"] is False
    assert account["reconnect_by"] > account["connected_at"]


def test_connect_links_only_work_once(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    url = client.post("/api/spotify/connect").json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    client.get("/auth/spotify/callback", params={"code": "abc", "state": state})
    again = client.get("/auth/spotify/callback", params={"code": "abc", "state": state})
    assert "That link has expired" in again.text


def test_made_up_connect_links_store_nothing(client: TestClient) -> None:
    page = client.get("/auth/spotify/callback", params={"code": "abc", "state": "forged"})
    assert "That link has expired" in page.text
    sign_in(client, *ADMIN)
    assert client.get("/api/spotify/account").json()["connected"] is False


def test_declining_on_spotifys_page(client: TestClient) -> None:
    page = client.get("/auth/spotify/callback", params={"error": "access_denied"})
    assert "Spotify wasn't connected" in page.text


def test_spotify_signing_the_account_out(client: TestClient, spotify: FakeSpotify, monkeypatch):
    connect(client)
    spotify.refresh_fails = True
    # Make the stored access token look expired, so GuildFM has to refresh it.
    monkeypatch.setattr(client.app.state.spotify, "_clock", lambda: 10**12)
    account = client.get("/api/spotify/account").json()
    assert account["connected"] is False
    assert "Connect it again" in account["problem"]


def test_disconnecting(client: TestClient) -> None:
    connect(client)
    assert client.delete("/api/spotify/account").status_code == 204
    assert client.get("/api/spotify/account").json()["connected"] is False


@pytest.mark.parametrize(
    ("who", "view", "change"), [("user", 403, 403), ("curator", 200, 403), ("admin", 200, 200)]
)
def test_who_can_see_and_connect_the_account(client: TestClient, people, who, view, change):
    sign_in(client, *people[who])
    assert client.get("/api/spotify/account").status_code == view
    assert client.post("/api/spotify/connect").status_code == change


def test_songs_that_cant_play_here_are_left_out_of_search(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    titles = [
        t["title"] for t in client.get("/api/search", params={"q": "song 2"}).json()["tracks"]
    ]
    assert "Song 20" in titles
    assert "Song 21" not in titles  # Spotify says it can't play here
