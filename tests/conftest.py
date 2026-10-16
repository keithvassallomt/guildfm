from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient

from guildfm.ai import AIClient
from guildfm.awareness import Awareness
from guildfm.config import Settings
from guildfm.main import create_app
from guildfm.speech import SpeechClient
from guildfm.spotify import SpotifyClient
from tests.fakes import FakeElevenLabs, FakeOpenAI, FakeSpeakers, FakeSpotify, FakeWeather
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
        audio_loudness=None,  # the fakes' MP3s are silence; tests compare them byte for byte
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
def openai() -> FakeOpenAI:
    return FakeOpenAI()


@pytest.fixture
def weather() -> FakeWeather:
    return FakeWeather()


@pytest.fixture
def elevenlabs() -> FakeElevenLabs:
    return FakeElevenLabs()


def fake(service) -> httpx2.AsyncClient:
    """An HTTP client that talks to a fake service instead of the internet."""
    return httpx2.AsyncClient(transport=httpx2.MockTransport(service))


@pytest.fixture
def start(
    settings: Settings,
    speakers: FakeSpeakers,
    spotify: FakeSpotify,
    openai: FakeOpenAI,
    weather: FakeWeather,
    elevenlabs: FakeElevenLabs,
    clock: Clock,
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

        def voices(request: httpx2.Request) -> httpx2.Response:
            if request.url.host == "api.elevenlabs.io":
                return elevenlabs(request)
            return openai(request)

        speech = SpeechClient(
            api_key="test",
            model="gpt-4o-mini-tts",
            media_dir=settings.data_dir / "media",
            http=fake(voices),
            eleven_key="eleven-test",
        )
        ai = AIClient("test", "gpt-6-astra", "low", http=fake(openai))
        awareness = Awareness(ai, http=fake(weather))
        app = create_app(
            settings,
            speakers,
            api,
            poll=False,
            now=clock,
            speech=speech,
            ai=ai,
            awareness=awareness,
        )
        return TestClient(app)

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
