from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient

from guildfm.config import Settings
from guildfm.main import create_app
from guildfm.spotify import SpotifyClient
from tests.fakes import FakeSpeakers, FakeSpotify
from tests.helpers import ADMIN, PASSWORD, register, sign_in


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        openai_api_key="test",
        spotify_client_id="test",
        spotify_client_secret="test",
        guildfm_secret_key="test",
        guildfm_admin_username=ADMIN[0],
        guildfm_admin_password=ADMIN[1],
        data_dir=tmp_path / "data",
        web_dist=tmp_path / "dist",
    )


@pytest.fixture
def speakers() -> FakeSpeakers:
    return FakeSpeakers()


class Clock:
    """The time as the app sees it. Tests move it about."""

    def __init__(self) -> None:
        # A Tuesday morning: inside the default playback hours, 08:00 to 18:00 on weekdays.
        self.now = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def spotify() -> FakeSpotify:
    return FakeSpotify()


@pytest.fixture
def start(
    settings: Settings, speakers: FakeSpeakers, spotify: FakeSpotify, clock: Clock
) -> Callable[[], TestClient]:
    """Starts GuildFM, use it with `with`. Starting it again is a restart: same data, same
    speakers."""

    def start() -> TestClient:
        api = SpotifyClient(
            client_id="test",
            client_secret="test",
            redirect_uri=settings.spotify_redirect_uri,
            market="GB",
            http=httpx2.AsyncClient(transport=httpx2.MockTransport(spotify)),
        )
        return TestClient(create_app(settings, speakers, api, poll=False, now=clock))

    return start


@pytest.fixture
def client(start: Callable[[], TestClient]) -> Iterator[TestClient]:
    with start() as client:
        yield client


@pytest.fixture
def people(client: TestClient) -> dict[str, tuple[str, str]]:
    """A user and a curator alongside the seeded admin. Leaves the client signed out."""
    register(client, "user")
    curator = register(client, "curator")
    sign_in(client, *ADMIN)
    client.patch(f"/api/users/{curator['id']}", json={"role": "curator"}).raise_for_status()
    client.cookies.clear()
    return {"user": ("user", PASSWORD), "curator": ("curator", PASSWORD), "admin": ADMIN}
