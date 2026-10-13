import sqlite3

from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

from guildfm.config import Settings
from guildfm.db import MIGRATIONS
from guildfm.main import create_app


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_migrations_run_on_startup(client: TestClient, settings: Settings) -> None:
    head = ScriptDirectory(str(MIGRATIONS)).get_current_head()
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (head,)


def test_unbuilt_front_end_says_so(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 503
    assert "make build" in response.text


def test_serves_built_front_end(settings: Settings) -> None:
    settings.web_dist.mkdir(parents=True)
    (settings.web_dist / "index.html").write_text("<html>GuildFM</html>")
    (settings.web_dist / "assets").mkdir()
    (settings.web_dist / "assets" / "app.js").write_text("console.log('hi')")
    (settings.web_dist.parent / "secret.txt").write_text("nope")

    with TestClient(create_app(settings)) as client:
        assert client.get("/assets/app.js").text == "console.log('hi')"
        # Client-side routes fall back to index.html.
        assert client.get("/search").text == "<html>GuildFM</html>"
        # Unknown API paths are real 404s, not the front end.
        assert client.get("/api/nope").status_code == 404
        # Paths can't escape the build folder.
        assert "nope" not in client.get("/..%2Fsecret.txt").text
