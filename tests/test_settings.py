import pytest
from fastapi.testclient import TestClient

from guildfm.prefs import DEFAULTS
from tests.fakes import spotify_id
from tests.helpers import ADMIN, sign_in


def test_settings_start_at_the_defaults(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    body = client.get("/api/settings").json()
    assert body["values"] == DEFAULTS
    assert body["values"]["request_cap"] == 5
    assert body["values"]["schedule"]["mon"] == {"on": True, "start": "08:00", "end": "18:00"}
    assert body["values"]["schedule"]["sat"]["on"] is False
    assert "cedar" in body["voices"]
    assert "Europe/London" in body["timezones"]


def test_changing_a_setting(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    body = client.patch("/api/settings", json={"request_cap": 2, "allow_explicit": False}).json()
    assert body["values"]["request_cap"] == 2
    assert body["values"]["allow_explicit"] is False
    # Everything else stays as it was.
    assert body["values"]["downvote_threshold"] == -3


def test_new_settings_take_effect(client: TestClient, people) -> None:
    sign_in(client, *ADMIN)
    client.patch("/api/settings", json={"request_cap": 1}).raise_for_status()
    sign_in(client, *people["user"])
    client.post("/api/queue", json={"track_id": spotify_id("fm1")}).raise_for_status()
    response = client.post("/api/queue", json={"track_id": spotify_id("fm2")})
    assert response.status_code == 409
    assert client.get("/api/queue").json()["request_cap"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"request_cap": 0},
        {"downvote_threshold": 1},
        {"queue_runs_out": "panic"},
        {"announcement_voice": "darth"},
        {"timezone": "Mars/Olympus_Mons"},
        {"weather_location": ""},
        {"schedule": {"mon": {"on": True, "start": "08:00", "end": "18:00"}}},
    ],
)
def test_bad_settings_are_refused(client: TestClient, change: dict) -> None:
    sign_in(client, *ADMIN)
    assert client.patch("/api/settings", json=change).status_code == 422


def test_closing_before_opening_is_refused(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    week = {day: {"on": True, "start": "08:00", "end": "18:00"} for day in DEFAULTS["schedule"]}
    week["wed"] = {"on": True, "start": "18:00", "end": "08:00"}
    response = client.patch("/api/settings", json={"schedule": week})
    assert response.status_code == 422
    assert "Opening time has to come before closing time." in response.text


@pytest.mark.parametrize("who", ["user", "curator"])
def test_only_admins_see_and_change_settings(client: TestClient, people, who) -> None:
    sign_in(client, *people[who])
    assert client.get("/api/settings").status_code == 403
    assert client.patch("/api/settings", json={"request_cap": 9}).status_code == 403
