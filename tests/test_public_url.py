"""With a public address set, browsers opening GuildFM over plain HTTP by name are sent there,
while the speakers, open pages' API calls and Spotify's sign-in carry on as they are."""

from collections.abc import Callable

from fastapi.testclient import TestClient

from guildfm.config import Settings

PUBLIC = "https://guildfm.com"


def opened(start: Callable[[], TestClient], settings: Settings) -> TestClient:
    settings.public_url = PUBLIC
    return start()


def test_a_page_by_name_goes_to_the_public_address(start, settings: Settings) -> None:
    with opened(start, settings) as client:
        response = client.get("http://guildfm.local/queue?tab=mine", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == f"{PUBLIC}/queue?tab=mine"


def test_the_speakers_and_the_api_are_left_alone(start, settings: Settings) -> None:
    with opened(start, settings) as client:
        by_ip = client.get("http://10.240.1.61/", follow_redirects=False)
        media = client.get("http://guildfm.local/media/speech/none.mp3", follow_redirects=False)
        api = client.get("http://guildfm.local/api/health", follow_redirects=False)
        spotify = client.get("http://127.0.0.1:8000/", follow_redirects=False)
    assert by_ip.status_code != 307
    assert media.status_code == 404
    assert api.status_code == 200
    assert spotify.status_code != 307


def test_https_from_caddy_is_served(start, settings: Settings) -> None:
    with opened(start, settings) as client:
        response = client.get("https://guildfm.com/", follow_redirects=False)
    assert response.status_code != 307


def test_nothing_moves_without_a_public_address(client: TestClient) -> None:
    assert client.get("http://guildfm.local/", follow_redirects=False).status_code != 307
