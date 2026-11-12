import sqlite3

from fastapi.testclient import TestClient

from guildfm import __version__, news
from tests.fakes import spotify_id
from tests.helpers import ADMIN, PASSWORD, register, sign_in


def test_admin_is_seeded_from_settings(client: TestClient) -> None:
    me = sign_in(client, *ADMIN)
    assert me["role"] == "admin"
    assert "manage_users" in me["permissions"]


def test_register_signs_you_in_as_a_user(client: TestClient) -> None:
    me = register(client, "Priya")
    assert me["username"] == "priya"
    assert me["role"] == "user"
    assert me["announce_requests"] is True
    assert client.get("/api/me").json()["id"] == me["id"]


def test_usernames_are_unique_and_case_insensitive(client: TestClient) -> None:
    register(client, "priya")
    response = client.post(
        "/api/auth/register",
        json={"username": "PRIYA", "display_name": "Other Priya", "password": PASSWORD},
    )
    assert response.status_code == 409
    assert sign_in(client, "PrIyA")["username"] == "priya"


def test_registration_explains_bad_input(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register", json={"username": "p", "display_name": "P", "password": "short"}
    )
    assert response.status_code == 422
    messages = [error["msg"] for error in response.json()["detail"]]
    assert "Use at least 8 characters for your password." in messages
    assert any(message.startswith("Usernames are 3 to 32") for message in messages)


def test_wrong_password_is_refused(client: TestClient) -> None:
    register(client, "priya")
    client.cookies.clear()
    for username in ("priya", "nobody"):
        response = client.post("/api/auth/login", json={"username": username, "password": "nope"})
        assert response.status_code == 401
        assert response.json()["detail"] == "That username and password don't match."


def test_sign_out(client: TestClient) -> None:
    register(client, "priya")
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/me").status_code == 401


def test_update_profile(client: TestClient) -> None:
    register(client, "priya")
    me = client.patch("/api/me", json={"display_name": "  Priya   S  ", "announce_requests": False})
    assert me.status_code == 200
    assert me.json()["display_name"] == "Priya S"
    assert me.json()["announce_requests"] is False


def test_new_account_must_replace_its_temporary_password(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    created = client.post("/api/users", json={"username": "lena", "display_name": "Lena"}).json()
    temporary = created["temporary_password"]

    me = sign_in(client, "lena", temporary)
    assert me["must_change_password"] is True
    # Until then, only reading your own account and choosing a password work.
    assert client.get("/api/me").status_code == 200
    assert client.patch("/api/me", json={"display_name": "L"}).status_code == 403

    me = client.post("/api/me/password", json={"password": "a-better-one"}).json()
    assert me["must_change_password"] is False
    assert client.patch("/api/me", json={"display_name": "L"}).status_code == 200
    sign_in(client, "lena", "a-better-one")


def test_choosing_a_password_is_only_for_temporary_ones(client: TestClient) -> None:
    register(client, "priya")
    response = client.post("/api/me/password", json={"password": "new-password"})
    assert response.status_code == 403


def test_deleting_a_user(client: TestClient) -> None:
    priya = register(client, "priya")
    old_cookies = dict(client.cookies)

    sign_in(client, *ADMIN)
    assert client.delete(f"/api/users/{priya['id']}").status_code == 204
    assert "priya" not in [user["username"] for user in client.get("/api/users").json()]
    assert client.delete(f"/api/users/{priya['id']}").status_code == 404

    client.cookies.clear()
    client.cookies.update(old_cookies)
    assert client.get("/api/me").status_code == 401
    # The username is free again.
    register(client, "priya")


def test_renaming_someone(client: TestClient, people, openai) -> None:
    priya = register(client, "priya")
    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()
    priya_cookies = dict(client.cookies)
    openai.names["Big Ricky"] = "vulgar"  # not asked: names admins give aren't checked

    sign_in(client, *ADMIN)
    rename = f"/api/users/{priya['id']}/name"
    taken = client.put(rename, json={"username": "User", "display_name": "Priya"})
    assert (taken.status_code, taken.json()["detail"]) == (409, "That username is taken.")
    assert client.put(rename, json={"username": "p", "display_name": "Priya"}).status_code == 422
    renamed = client.put(rename, json={"username": " Big.Ricky ", "display_name": " Big  Ricky "})
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["username"], renamed.json()["display_name"]) == (
        "big.ricky",
        "Big Ricky",
    )
    # Keeping the same username is fine.
    client.put(rename, json={"username": "big.ricky", "display_name": "Ricky"}).raise_for_status()

    # Their request shows the new name.
    queue = client.get("/api/queue").json()
    entries = [queue["playing"], queue["next"], *queue["waiting"]]
    assert [e["requested_by"]["display_name"] for e in entries if e] == ["Ricky"]

    # They stay signed in, and sign in with the new username from now on.
    client.cookies.clear()
    client.cookies.update(priya_cookies)
    assert client.get("/api/me").json()["display_name"] == "Ricky"
    old = client.post("/api/auth/login", json={"username": "priya", "password": PASSWORD})
    assert old.status_code == 401
    assert sign_in(client, "Big.Ricky")["display_name"] == "Ricky"


def test_password_reset_signs_the_user_out_everywhere(client: TestClient) -> None:
    priya = register(client, "priya")
    old_cookies = dict(client.cookies)

    sign_in(client, *ADMIN)
    reset = client.post(f"/api/users/{priya['id']}/reset-password").json()

    client.cookies.clear()
    client.cookies.update(old_cookies)
    assert client.get("/api/me").status_code == 401
    assert sign_in(client, "priya", reset["temporary_password"])["must_change_password"] is True


# Photos

JPEG = b"\xff\xd8\xff\xe0" + bytes(200)
PNG = b"\x89PNG\r\n\x1a\n" + bytes(200)


def put_photo(client: TestClient, data: bytes, kind: str = "image/jpeg"):
    return client.put("/api/me/avatar", content=data, headers={"content-type": kind})


def test_a_photo_beside_your_name(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    url = put_photo(client, JPEG).json()["avatar_url"]
    assert url.startswith("/media/avatars/") and url.endswith(".jpg")
    assert client.get(url).content == JPEG
    assert client.get("/api/me").json()["avatar_url"] == url

    # Shown with their requests.
    client.post("/api/queue", json={"track_id": spotify_id("dreams")}).raise_for_status()
    assert client.get("/api/queue").json()["waiting"][0]["requested_by"]["avatar_url"] == url

    # A new photo replaces the old one, file and all.
    newer = put_photo(client, PNG, "image/png").json()["avatar_url"]
    assert newer.endswith(".png") and newer != url
    assert client.get(url).status_code == 404

    assert client.delete("/api/me/avatar").json()["avatar_url"] is None
    assert client.get(newer).status_code == 404


def test_only_pictures_and_not_huge_ones(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    assert put_photo(client, b"just some text", "text/plain").status_code == 415
    assert put_photo(client, JPEG + bytes(2 * 1024 * 1024)).status_code == 413
    assert client.get("/api/me").json()["avatar_url"] is None


def test_deleting_someone_deletes_their_photo(client: TestClient, people) -> None:
    sign_in(client, *people["user"])
    url = put_photo(client, JPEG).json()["avatar_url"]
    user = client.get("/api/me").json()
    sign_in(client, *ADMIN)
    client.delete(f"/api/users/{user['id']}").raise_for_status()
    assert client.get(url).status_code == 404


def test_whats_new_is_shown_once(client: TestClient, settings) -> None:
    # A new account has nothing new to hear about.
    assert register(client, "dan")["news_seen"] == __version__
    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        db.execute("UPDATE users SET news_seen = '0.1.2' WHERE username = 'dan'")
    assert client.get("/api/me").json()["news_seen"] == "0.1.2"

    assert client.post("/api/me/news").json()["news_seen"] == __version__
    assert client.get("/api/me").json()["news_seen"] == __version__


def test_notes_wait_for_their_version_and_are_shown_newest_first(tmp_path) -> None:
    for version in ("0.1.1", "0.1.3", "0.1.4", "0.1.10", "0.2.0"):
        (tmp_path / f"{version}.md").write_text(f"What's new in {version}")
    found = news.unseen("0.1.2", "0.1.10", tmp_path)
    # Not 0.1.1, already seen, nor 0.2.0, not out yet. At most the last three.
    assert [note["version"] for note in found] == ["0.1.10", "0.1.4", "0.1.3"]
    assert news.unseen("0.1.2", "0.1.3", tmp_path) == [
        {"version": "0.1.3", "text": "What's new in 0.1.3"}
    ]
    assert news.unseen("0.1.10", "0.1.10", tmp_path) == []


def test_whats_new_is_there_until_its_seen(client: TestClient, settings, tmp_path, monkeypatch):
    monkeypatch.setattr(news, "FOLDER", tmp_path)
    (tmp_path / f"{__version__}.md").write_text("## Vote on what's playing")
    register(client, "dan")
    assert client.get("/api/me/news").json() == {"notes": []}  # new, so nothing's new to them

    with sqlite3.connect(settings.data_dir / "guildfm.db") as db:
        db.execute("UPDATE users SET news_seen = '0.0.1' WHERE username = 'dan'")
    notes = client.get("/api/me/news").json()["notes"]
    assert notes == [{"version": __version__, "text": "## Vote on what's playing"}]
    assert client.get("/api/me/news").json()["notes"] == notes  # until it's seen
    client.post("/api/me/news").raise_for_status()
    assert client.get("/api/me/news").json() == {"notes": []}
