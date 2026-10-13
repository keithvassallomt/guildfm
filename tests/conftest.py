from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from guildfm.config import Settings
from guildfm.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        openai_api_key="test",
        spotify_client_id="test",
        spotify_client_secret="test",
        guildfm_secret_key="test",
        guildfm_admin_password="test",
        data_dir=tmp_path / "data",
        web_dist=tmp_path / "dist",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as client:
        yield client
