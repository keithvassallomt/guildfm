from fastapi.testclient import TestClient

from tests.fakes import FakeOpenAI
from tests.helpers import ADMIN, sign_in


def make_station(client: TestClient, **fields) -> dict:
    body = {"name": "Lunchtime Grooves", "description": "Upbeat soul for the lunch hour.", **fields}
    response = client.post("/api/stations", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def settle(client: TestClient) -> None:
    client.portal.call(client.app.state.covers.settle)


def station(client: TestClient, station_id: int) -> dict:
    return client.get(f"/api/stations/{station_id}").json()


def test_a_new_station_gets_a_cover(client: TestClient, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    made = make_station(client)
    assert made["art_url"] is None  # painted in the background
    settle(client)

    url = station(client, made["id"])["art_url"]
    assert url.startswith("/media/covers/") and url.endswith(".webp")
    assert client.get(url).content == openai.painted(1)
    asked = openai.images[0]
    assert (asked["model"], asked["size"], asked["quality"]) == (
        "gpt-image-2.5-flare",
        "1024x1024",
        "medium",
    )
    assert '"Lunchtime Grooves"' in asked["prompt"]
    assert "Upbeat soul for the lunch hour." in asked["prompt"]
    assert 'name, "Lunchtime Grooves", on it as the only words' in asked["prompt"]
    assert "No other text" in asked["prompt"]
    # On Now Playing's tiles too.
    tiles = client.get("/api/now").json()["stations"]
    assert next(t for t in tiles if t["id"] == made["id"])["art_url"] == url


def test_a_new_description_gets_a_new_cover(client: TestClient, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    made = make_station(client)
    settle(client)
    first = station(client, made["id"])["art_url"]

    body = {"name": "Lunchtime Grooves", "description": "Upbeat soul for the lunch hour."}
    client.put(f"/api/stations/{made['id']}", json=body | {"dj": True, "dj_name": "Della"})
    settle(client)
    assert len(openai.images) == 1  # the DJ isn't in the picture

    client.put(f"/api/stations/{made['id']}", json=body | {"description": "Mellow jazz."})
    settle(client)
    assert len(openai.images) == 2
    assert "Mellow jazz." in openai.images[1]["prompt"]
    second = station(client, made["id"])["art_url"]
    assert second != first
    assert client.get(first).status_code == 404  # the old one's gone


def test_another_cover_on_request(client: TestClient, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    made = make_station(client)
    settle(client)
    again = client.post(f"/api/stations/{made['id']}/cover").json()
    assert client.get(again["art_url"]).content == openai.painted(2)


def test_another_cover_from_the_editors_unsaved_details(client, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    made = make_station(client)
    settle(client)
    body = {"name": "Teatime Grooves", "description": "Soul for teatime."}
    client.post(f"/api/stations/{made['id']}/cover", json=body).raise_for_status()
    assert '"Teatime Grooves"' in openai.images[1]["prompt"]
    assert "Soul for teatime." in openai.images[1]["prompt"]
    assert station(client, made["id"])["name"] == "Lunchtime Grooves"  # not saved

    # Saving what it was painted from doesn't paint another; anything else does.
    client.put(f"/api/stations/{made['id']}", json=body).raise_for_status()
    settle(client)
    assert len(openai.images) == 2
    client.put(f"/api/stations/{made['id']}", json=body | {"name": "Supper Club"})
    settle(client)
    assert len(openai.images) == 3


def test_when_openai_cant_paint_the_station_carries_on(client, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    openai.images_down = True
    made = make_station(client)
    settle(client)
    assert station(client, made["id"])["art_url"] is None
    response = client.post(f"/api/stations/{made['id']}/cover")
    assert response.status_code == 502
    assert "No new cover this time" in response.json()["detail"]


def test_stations_without_covers_get_them_at_startup(client, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    openai.images_down = True
    make_station(client)
    settle(client)
    openai.images_down = False
    client.portal.call(client.app.state.covers.fill_in)
    stations = client.get("/api/stations").json()
    assert {s["name"] for s in stations if s["art_url"]} == {"Lunchtime Grooves", "AI picks"}
    prompts = [image["prompt"] for image in openai.images]
    assert any("Songs that follow on from what has been playing" in p for p in prompts)


def test_deleting_a_station_deletes_its_cover(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    made = make_station(client)
    settle(client)
    url = station(client, made["id"])["art_url"]
    client.delete(f"/api/stations/{made['id']}").raise_for_status()
    assert client.get(url).status_code == 404
