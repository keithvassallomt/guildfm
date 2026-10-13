import pytest
from fastapi.testclient import TestClient

from guildfm.models import Role
from guildfm.permissions import ROLE_PERMISSIONS, Permission
from tests.helpers import ADMIN, register, sign_in

# The permissions table from stream.md, row by row: (permission, user, curator, admin).
TABLE = [
    (Permission.ADD_TRACKS, True, True, True),
    (Permission.VOTE, True, True, True),
    (Permission.REMOVE_OWN_TRACKS, True, True, True),
    (Permission.MANAGE_QUEUE, False, True, True),
    (Permission.MANAGE_PLAYLISTS, False, True, True),
    (Permission.CREATE_STATIONS, False, True, True),
    (Permission.SWITCH_SOURCE, False, True, True),
    (Permission.CONTROL_PLAYBACK, False, False, True),
    (Permission.ANNOUNCE, False, False, True),
    (Permission.MANAGE_USERS, False, False, True),
    (Permission.CHANGE_SETTINGS, False, False, True),
]


def test_table_covers_every_permission() -> None:
    assert {row[0] for row in TABLE} == set(Permission)


@pytest.mark.parametrize(("permission", "user", "curator", "admin"), TABLE)
def test_roles_match_the_spec(permission: Permission, user: bool, curator: bool, admin: bool):
    assert (permission in ROLE_PERMISSIONS[Role.USER]) is user
    assert (permission in ROLE_PERMISSIONS[Role.CURATOR]) is curator
    assert (permission in ROLE_PERMISSIONS[Role.ADMIN]) is admin


def test_me_lists_your_permissions(client: TestClient, people) -> None:
    me = sign_in(client, *people["curator"])
    assert set(me["permissions"]) == set(ROLE_PERMISSIONS[Role.CURATOR])


USER_ROUTES = [
    ("get", "/api/users", None),
    ("post", "/api/users", {"username": "lena", "display_name": "Lena"}),
    ("patch", "/api/users/{id}", {"role": "curator"}),
    ("post", "/api/users/{id}/reset-password", None),
]


@pytest.mark.parametrize(("method", "path", "body"), USER_ROUTES)
@pytest.mark.parametrize(("who", "status"), [(None, 401), ("user", 403), ("curator", 403)])
def test_only_admins_manage_users(client: TestClient, people, method, path, body, who, status):
    target = register(client, "target")
    client.cookies.clear()
    if who:
        sign_in(client, *people[who])
    response = client.request(method, path.format(id=target["id"]), json=body)
    assert response.status_code == status


@pytest.mark.parametrize(("method", "path", "body"), USER_ROUTES)
def test_admins_manage_users(client: TestClient, people, method, path, body) -> None:
    target = register(client, "target")
    sign_in(client, *ADMIN)
    response = client.request(method, path.format(id=target["id"]), json=body)
    assert response.status_code in (200, 201), response.text


def test_admins_cant_change_their_own_account(client: TestClient) -> None:
    me = sign_in(client, *ADMIN)
    assert client.patch(f"/api/users/{me['id']}", json={"role": "user"}).status_code == 403
    assert client.post(f"/api/users/{me['id']}/reset-password").status_code == 403


def test_role_changes_apply_straight_away(client: TestClient, people) -> None:
    user = sign_in(client, *people["user"])
    sign_in(client, *ADMIN)
    client.patch(f"/api/users/{user['id']}", json={"role": "admin"}).raise_for_status()
    assert "manage_users" in sign_in(client, *people["user"])["permissions"]
    assert client.get("/api/users").status_code == 200
