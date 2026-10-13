"""GuildFM: office music, voted on by everyone."""

from importlib.metadata import version

__version__ = version("guildfm")


def main() -> None:
    """Run GuildFM with the host and port from settings."""
    import uvicorn

    from guildfm.config import get_settings

    settings = get_settings()
    uvicorn.run("guildfm.main:create_app", factory=True, host=settings.host, port=settings.port)
