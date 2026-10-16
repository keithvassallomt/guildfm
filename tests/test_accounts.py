from fastapi.testclient import TestClient

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
