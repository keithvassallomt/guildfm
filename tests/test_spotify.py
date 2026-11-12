import sqlite3
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

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


def test_search_pages_ten_at_a_time(client: TestClient, people, spotify) -> None:
    sign_in(client, *people["user"])
    pages, offset = [], 0
    while offset is not None:
        page = client.get("/api/search", params={"q": "fleetwood", "offset": offset}).json()
        pages.append(page)
        offset = page["next_offset"]
    # 23 songs, one of which can't play here. One call to Spotify each.
    assert [len(page["tracks"]) for page in pages] == [10, 10, 2]
    assert [page["next_offset"] for page in pages] == [10, 20, None]
    assert [len(page["artists"]) for page in pages] == [1, 0, 0]
    assert len({t["id"] for page in pages for t in page["tracks"]}) == 22
    assert spotify.searches == ["fleetwood"] * 3


def test_the_same_search_is_answered_from_memory(client: TestClient, people, spotify) -> None:
    sign_in(client, *people["user"])
    for query in ("dreams", "Dreams ", "humble", "dreams"):
        client.get("/api/search", params={"q": query}).raise_for_status()
    client.get("/api/search", params={"q": "dreams", "offset": 10}).raise_for_status()
    assert spotify.searches == ["dreams", "humble", "dreams"]  # the last is a new page


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


def test_nothing_goes_to_spotify_until_its_wait_is_over(
    client: TestClient, people, spotify: FakeSpotify
) -> None:
    api = client.app.state.spotify
    now = datetime(2026, 11, 11, 14, 45, tzinfo=ZoneInfo("Europe/London")).timestamp()
    api._clock = lambda: now
    sign_in(client, *people["user"])
    client.get("/api/search", params={"q": "dreams"}).raise_for_status()
    spotify.busy, spotify.retry_after = True, "64890"  # 18 hours
    assert client.get("/api/search", params={"q": "humble"}).status_code == 503

    spotify.busy = False
    response = client.get("/api/search", params={"q": "fleetwood"})
    assert response.status_code == 503
    assert response.json()["detail"] == "Spotify has paused searching until 08:47 tomorrow."
    # A search made before the pause is still answered, from memory.
    assert client.get("/api/search", params={"q": "dreams"}).status_code == 200
    assert spotify.searches == ["dreams", "humble"]  # fleetwood was never sent

    sign_in(client, *ADMIN)
    client.patch("/api/settings", json={"timezone": "Europe/Malta"}).raise_for_status()
    response = client.get("/api/search", params={"q": "fleetwood"})
    assert response.json()["detail"] == "Spotify has paused searching until 09:47 tomorrow."
    assert "Spotify has paused searching" in client.get("/api/status").text

    now += 64890
    assert client.get("/api/search", params={"q": "fleetwood"}).status_code == 200
    assert spotify.searches == ["dreams", "humble", "fleetwood"]


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


def test_an_account_the_app_wont_serve(client: TestClient, spotify: FakeSpotify) -> None:
    spotify.unlisted = True
    page = connect(client)
    assert "Spotify wasn't connected" in page
    assert "Users and Access" in page
    assert client.get("/api/spotify/account").json()["connected"] is False


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
