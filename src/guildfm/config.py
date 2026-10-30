from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuration, read from the environment and the repo's .env file."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    openai_api_key: SecretStr
    # OpenAI's text to speech model, for announcements and the DJ.
    openai_tts_model: str = "gpt-4o-mini-tts"
    # OpenAI's model for picking songs, writing the DJ's lines and reading the music news, and
    # how hard it thinks. Leave the effort empty for a model that doesn't take one.
    openai_model: str = "gpt-6-astra"
    openai_effort: str = "low"
    # OpenAI's image model, for stations' covers, and how carefully it paints.
    openai_image_model: str = "gpt-image-2.5-flare"
    openai_image_quality: str = "medium"
    # OpenAI's speech to text model, for listening for the words in a generated jingle.
    openai_hearing_model: str = "gpt-4o-transcribe"
    # ElevenLabs, for the account's own voices alongside OpenAI's. Optional: without a key, only
    # OpenAI's voices are offered. The model has to understand audio tags such as [laughs].
    elevenlabs_api_key: SecretStr = SecretStr("")
    elevenlabs_model: str = "eleven_v4"
    # ElevenLabs' music model, for the jingle generator.
    elevenlabs_music_model: str = "music_v2_5"
    # How loud voices and uploaded jingles are made, in LUFS, so they sit at about the music's
    # level. Needs ffmpeg; empty leaves them as they come.
    audio_loudness: float | None = -14.0
    spotify_client_id: str
    spotify_client_secret: SecretStr
    spotify_redirect_uri: str = "http://127.0.0.1:8000/auth/spotify/callback"
    # Search only shows tracks playable in this country (ISO 3166 code).
    spotify_market: str = "GB"
    guildfm_secret_key: SecretStr
    guildfm_admin_username: str = "admin"
    guildfm_admin_password: SecretStr

    host: str = "0.0.0.0"
    port: int = 8000
    # Where people open GuildFM over HTTPS, such as https://guildfm.com behind Caddy. Browsers
    # opening a page over plain HTTP by name are sent there. Empty leaves them where they are.
    public_url: str = ""

    # Comma-separated speaker addresses. Empty means find them on the network.
    sonos_hosts: str = ""
    # How Spotify is linked in this Sonos household; read from tracks the Sonos app queued.
    sonos_spotify_sid: int = 9
    sonos_spotify_sn: int = 1
    data_dir: Path = ROOT / "data"
    # Where the daily backups go. Empty means a "backups" folder in the data folder; somewhere on
    # another disk or a network share is safer.
    backup_dir: Path | None = None
    web_dist: Path = ROOT / "web" / "dist"

    @field_validator("audio_loudness", "backup_dir", mode="before")
    @classmethod
    def _empty_means_none(cls, value):
        """`AUDIO_LOUDNESS=` turns levelling off, and `BACKUP_DIR=` means the default."""
        return None if value == "" else value

    @property
    def sonos_host_list(self) -> list[str]:
        return [host.strip() for host in self.sonos_hosts.split(",") if host.strip()]

    @property
    def backups(self) -> Path:
        return self.backup_dir or self.data_dir / "backups"

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
