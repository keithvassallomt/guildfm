from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from guildfm.config import Settings
from guildfm.main import create_app
from tests.fakes import FakeSpeakers
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


@pytest.fixture
def client(settings: Settings, speakers: FakeSpeakers) -> Iterator[TestClient]:
    with TestClient(create_app(settings, speakers)) as client:
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
