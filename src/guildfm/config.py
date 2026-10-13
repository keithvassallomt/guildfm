from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuration, read from the environment and the repo's .env file."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    openai_api_key: SecretStr
    spotify_client_id: str
    spotify_client_secret: SecretStr
    spotify_redirect_uri: str = "http://127.0.0.1:8000/auth/spotify/callback"
    guildfm_secret_key: SecretStr
    guildfm_admin_username: str = "admin"
    guildfm_admin_password: SecretStr

    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: Path = ROOT / "data"
    web_dist: Path = ROOT / "web" / "dist"

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.data_dir / 'guildfm.db'}"

    @property
    def sync_database_url(self) -> str:
        """The same database for tools that need a synchronous driver, such as Alembic."""
        return self.database_url.replace("sqlite+aiosqlite", "sqlite", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
