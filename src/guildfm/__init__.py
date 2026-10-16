"""GuildFM: office music, voted on by everyone."""

from importlib.metadata import version

__version__ = version("guildfm")


def main() -> None:
    """Run GuildFM with the host and port from settings, or with `backup`, make a backup."""
    import argparse

    parser = argparse.ArgumentParser(prog="guildfm", description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        choices=["serve", "backup"],
        default="serve",
        help="serve (the default) runs GuildFM; backup makes a backup straight away",
    )
    command = parser.parse_args().command

    from guildfm.config import get_settings

    settings = get_settings()
    if command == "backup":
        from datetime import datetime

        from guildfm.backups import back_up

        print(back_up(settings.data_dir, settings.backups, datetime.now()))
        return

    import uvicorn

    uvicorn.run("guildfm.main:create_app", factory=True, host=settings.host, port=settings.port)
