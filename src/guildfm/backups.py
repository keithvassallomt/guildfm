"""Backups: a zip of the database and the uploaded media (jingles, station covers and profile
photos). Speech clips are left out, since they're made again when needed.

GuildFM makes one a day while it runs, and keeps the last two weeks. `guildfm backup` makes one
straight away. To restore one, stop GuildFM and unzip it into the data folder.
"""

import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

KEPT = 14
NAMED = "guildfm-%Y-%m-%d-%H%M%S"  # each is named after when it was made
MEDIA = ("jingles", "covers", "avatars")  # inside the media folder
DATABASE = "guildfm.db"


def back_up(data_dir: Path, folder: Path, when: datetime) -> Path:
    """Make a backup in `folder`, named after `when`, and clear out all but the latest few."""
    database = data_dir / DATABASE
    if not database.exists():
        raise FileNotFoundError(f"There's no database at {database} to back up.")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{when:{NAMED}}.zip"
    draft = target.with_suffix(".part")
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / DATABASE
        # SQLite's own backup, which is safe while GuildFM is using the database.
        with closing(sqlite3.connect(database)) as live, closing(sqlite3.connect(copy)) as saved:
            live.backup(saved)
        with zipfile.ZipFile(draft, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(copy, DATABASE)
            for name in MEDIA:
                for path in sorted((data_dir / "media" / name).rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(data_dir).as_posix())
    draft.replace(target)
    for old in backups(folder)[:-KEPT]:
        old.unlink(missing_ok=True)
    return target


def backups(folder: Path) -> list[Path]:
    """The backups in `folder`, oldest first."""
    return sorted(path for path in folder.glob("guildfm-*.zip") if _named(path))


def made_at(backup: Path) -> datetime:
    """When `backup` was made, in local time."""
    return datetime.strptime(backup.stem, NAMED)


def _named(path: Path) -> bool:
    try:
        made_at(path)
    except ValueError:
        return False
    return True
