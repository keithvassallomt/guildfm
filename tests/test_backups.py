import os
import sqlite3
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from guildfm.backups import KEPT, back_up, backups, made_at
from guildfm.config import Settings
from tests.helpers import ADMIN, sign_in


def data_folder(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    (data / "media" / "jingles").mkdir(parents=True)
    (data / "media" / "speech").mkdir(parents=True)
    with sqlite3.connect(data / "guildfm.db") as db:
        db.execute("CREATE TABLE songs (title TEXT)")
        db.execute("INSERT INTO songs VALUES ('Dreams')")
    db.close()
    (data / "media" / "jingles" / "ident.mp3").write_bytes(b"ID3 jingle")
    (data / "media" / "speech" / "line.mp3").write_bytes(b"ID3 speech")
    return data


def test_a_backup_has_the_database_and_uploads(tmp_path: Path) -> None:
    data = data_folder(tmp_path)
    made = back_up(data, tmp_path / "backups", datetime(2026, 10, 16, 3, 0))
    assert made.name == "guildfm-2026-10-16-030000.zip"
    assert made_at(made) == datetime(2026, 10, 16, 3, 0)
    with zipfile.ZipFile(made) as archive:
        # Laid out like the data folder, so restoring is unzipping it there.
        assert sorted(archive.namelist()) == ["guildfm.db", "media/jingles/ident.mp3"]
        archive.extract("guildfm.db", tmp_path / "restored")
    with sqlite3.connect(tmp_path / "restored" / "guildfm.db") as db:
        assert db.execute("SELECT title FROM songs").fetchall() == [("Dreams",)]
    db.close()


def test_only_the_latest_are_kept(tmp_path: Path) -> None:
    data = data_folder(tmp_path)
    start = datetime(2026, 10, 1, 3, 0)
    for day in range(KEPT + 2):
        back_up(data, tmp_path / "backups", start + timedelta(days=day))
    (tmp_path / "backups" / "guildfm-notes.zip").write_bytes(b"not one of ours")
    kept = backups(tmp_path / "backups")
    assert len(kept) == KEPT
    assert made_at(kept[0]) == start + timedelta(days=2)


def test_housekeeping_backs_up_once_a_day(client: TestClient, settings: Settings) -> None:
    housekeeping = client.app.state.housekeeping
    now = datetime(2026, 10, 16, 9, 0).timestamp()
    housekeeping.clock = lambda: now
    client.portal.call(housekeeping.tick)
    assert [path.name for path in backups(settings.backups)] == ["guildfm-2026-10-16-090000.zip"]

    now += 23 * 60 * 60
    client.portal.call(housekeeping.tick)
    assert len(backups(settings.backups)) == 1
    now += 60 * 60
    client.portal.call(housekeeping.tick)
    assert len(backups(settings.backups)) == 2

    sign_in(client, *ADMIN)
    found = client.get("/api/status").json()["backups"]
    assert found["count"] == 2
    latest = datetime(2026, 10, 17, 9, 0).astimezone(UTC)  # named in the machine's time
    assert found["latest_at"] == latest.isoformat().replace("+00:00", "Z")


def test_housekeeping_clears_out_old_speech(client: TestClient, settings: Settings) -> None:
    speech = settings.data_dir / "media" / "speech"
    speech.mkdir(parents=True, exist_ok=True)
    old, new = speech / "old.mp3", speech / "new.mp3"
    old.write_bytes(b"ID3")
    new.write_bytes(b"ID3")
    month_ago = time.time() - 31 * 24 * 60 * 60
    os.utime(old, (month_ago, month_ago))
    client.portal.call(client.app.state.housekeeping.tick)
    assert not old.exists()
    assert new.exists()
