"""Through Cloudflare, only visitors from the office's own public address get in; everyone
else is told to join the office Wi-Fi. Requests that don't come through Cloudflare, like the
speakers', are left alone. The office's address can change, so GuildFM looks again."""

import asyncio
from collections.abc import Callable
from http.cookies import SimpleCookie

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from guildfm import office as office_module
from guildfm.main import create_app
from guildfm.office import Office
from tests.helpers import ADMIN, sign_in

OFFICE_V4 = "203.0.113.7"
OFFICE_V6 = "2001:db8:5:5b00::1"


class Addresses:
    """Stands in for looking the office's address up, and counts the lookups."""

    def __init__(self, *found: str) -> None:
        self.found = list(found)
        self.lookups = 0

    async def __call__(self) -> list[str]:
        self.lookups += 1
        return self.found


@pytest.fixture
def addresses() -> Addresses:
    return Addresses(OFFICE_V4, OFFICE_V6)


@pytest.fixture
def guarded(start: Callable[[], TestClient], addresses: Addresses, monkeypatch) -> TestClient:
    """The usual test app, with the office's address looked up from `addresses`."""
    real = create_app

    def with_office(*args, **kwargs):
        return real(*args, office=Office(addresses), **kwargs)

    monkeypatch.setattr("tests.conftest.create_app", with_office)
    with start() as client:
        yield client


def via_cloudflare(visitor: str) -> dict[str, str]:
    return {"Cf-Connecting-Ip": visitor}


def test_the_office_gets_in(guarded: TestClient) -> None:
    response = guarded.get("/api/health", headers=via_cloudflare(OFFICE_V4))
    assert response.status_code == 200


def test_any_phone_on_the_office_ipv6_network_gets_in(guarded: TestClient) -> None:
    response = guarded.get("/api/health", headers=via_cloudflare("2001:db8:5:5b00:abcd::9"))
    assert response.status_code == 200


def test_outsiders_are_told_to_join_the_wifi(guarded: TestClient) -> None:
    for visitor in ("198.51.100.20", "2001:db8:9::1", "nonsense"):
        response = guarded.get("/", headers=via_cloudflare(visitor))
        assert response.status_code == 403
        assert "TJardinePrivate" in response.text
    assert guarded.get("/api/health", headers=via_cloudflare("198.51.100.20")).status_code == 403


def test_outsiders_get_no_live_updates(guarded: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect),
        guarded.websocket_connect("/ws", headers=via_cloudflare("198.51.100.20")),
    ):
        pass


def test_the_office_network_and_speakers_are_left_alone(guarded: TestClient) -> None:
    assert guarded.get("http://10.240.1.61/api/health").status_code == 200
    assert guarded.get("http://guildfm.local/api/health").status_code == 200


def test_a_new_office_address_is_picked_up(
    guarded: TestClient, addresses: Addresses, monkeypatch
) -> None:
    assert guarded.get("/api/health", headers=via_cloudflare(OFFICE_V4)).status_code == 200
    monkeypatch.setattr(office_module, "RECHECK_SECONDS", 0)
    addresses.found = ["203.0.113.99"]
    assert guarded.get("/api/health", headers=via_cloudflare("203.0.113.99")).status_code == 200
    assert guarded.get("/api/health", headers=via_cloudflare(OFFICE_V4)).status_code == 403


def test_strangers_dont_make_it_look_up_every_time(addresses: Addresses) -> None:
    office = Office(addresses)

    async def visits() -> None:
        for _ in range(5):
            assert not await office.admits("198.51.100.20")
        assert await office.admits(OFFICE_V4)

    asyncio.run(visits())
    assert addresses.lookups == 1


def test_a_failed_lookup_keeps_everyone_outside_out() -> None:
    async def broken() -> list[str]:
        raise OSError("no internet")

    async def visit() -> bool:
        return await Office(broken).admits(OFFICE_V4)

    assert asyncio.run(visit()) is False


# Other ways in: confirming a location, or Safari showing the real address, each good for a day.

OFFICE_PLACE = {"latitude": 54.8925, "longitude": -2.9346}
NEARBY = {"latitude": 54.8929, "longitude": -2.9346, "accuracy": 20}  # about 45 m north
RELAY = "104.28.86.58"  # an iCloud Private Relay exit


def set_off_office(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    client.put("/api/settings/office-location", json={**OFFICE_PLACE, "accuracy": 15})
    client.cookies.clear()


def cookies_set(response) -> dict[str, str]:
    jar = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        jar.load(header)
    return {name: morsel.value for name, morsel in jar.items()}


def with_pass(visitor: str, value: str) -> dict[str, str]:
    return {**via_cloudflare(visitor), "Cookie": f"{office_module.PASS_COOKIE}={value}"}


def test_the_location_check_shows_once_the_office_is_set(guarded: TestClient) -> None:
    assert "Confirm my location" not in guarded.get("/", headers=via_cloudflare(RELAY)).text
    set_off_office(guarded)
    assert "Confirm my location" in guarded.get("/", headers=via_cloudflare(RELAY)).text


def test_confirming_a_location_lets_the_browser_in_until_midnight(
    guarded: TestClient, clock
) -> None:
    set_off_office(guarded)
    response = guarded.post("/office/here", json=NEARBY, headers=via_cloudflare(RELAY))
    assert response.json() == {"in": True}
    day_pass = cookies_set(response)[office_module.PASS_COOKIE]
    # From any address, since Private Relay changes it.
    for visitor in (RELAY, "104.28.86.99"):
        assert guarded.get("/api/health", headers=with_pass(visitor, day_pass)).status_code == 200
    # 09:00 UTC is 10:00 in London; midnight there is 23:00 UTC.
    clock.now = clock.now.replace(hour=22, minute=59)
    assert guarded.get("/api/health", headers=with_pass(RELAY, day_pass)).status_code == 200
    clock.now = clock.now.replace(hour=23, minute=1)
    assert guarded.get("/api/health", headers=with_pass(RELAY, day_pass)).status_code == 403


def test_far_or_rough_locations_are_turned_away(guarded: TestClient) -> None:
    set_off_office(guarded)
    far = {**NEARBY, "latitude": 54.9105}  # 2 km north
    response = guarded.post("/office/here", json=far, headers=via_cloudflare(RELAY))
    assert response.json()["why"] == "far"
    assert 1950 < response.json()["distance"] < 2050
    assert office_module.PASS_COOKIE not in cookies_set(response)
    rough = {**NEARBY, "accuracy": 3000}  # Precise Location off
    response = guarded.post("/office/here", json=rough, headers=via_cloudflare(RELAY))
    assert response.json() == {"in": False, "why": "rough", "accuracy": 3000}
    assert office_module.PASS_COOKIE not in cookies_set(response)


def test_no_location_check_until_the_office_is_set(guarded: TestClient) -> None:
    response = guarded.post("/office/here", json=NEARBY, headers=via_cloudflare(RELAY))
    assert response.json() == {"in": False, "why": "off"}
    response = guarded.post("/office/here", json={"latitude": 91}, headers=via_cloudflare(RELAY))
    assert response.status_code == 422


def test_a_made_up_pass_gets_nowhere(guarded: TestClient) -> None:
    for value in ("9999999999", "9999999999.forged", ""):
        assert guarded.get("/api/health", headers=with_pass(RELAY, value)).status_code == 403


def test_safari_showing_the_address_gets_a_day_pass(guarded: TestClient) -> None:
    turned_away = guarded.get("/", headers=via_cloudflare(RELAY))
    assert cookies_set(turned_away)[office_module.TURNED_AWAY_COOKIE] == "1"
    # Show IP Address reloads the page from the office's own address.
    note = {"Cookie": f"{office_module.TURNED_AWAY_COOKIE}=1"}
    back = guarded.get("/api/health", headers={**via_cloudflare(OFFICE_V4), **note})
    assert back.status_code == 200
    day_pass = cookies_set(back)[office_module.PASS_COOKIE]
    assert cookies_set(back)[office_module.TURNED_AWAY_COOKIE] == ""
    # The next reload goes through Private Relay again.
    assert guarded.get("/api/health", headers=with_pass(RELAY, day_pass)).status_code == 200


def test_the_office_gets_no_pass_it_doesnt_need(guarded: TestClient) -> None:
    response = guarded.get("/api/health", headers=via_cloudflare(OFFICE_V4))
    assert response.status_code == 200
    assert office_module.PASS_COOKIE not in cookies_set(response)


def test_the_safari_pictures_are_there_for_outsiders(guarded: TestClient) -> None:
    for name in ("iphone", "mac"):
        response = guarded.get(f"/office/{name}.webp", headers=via_cloudflare(RELAY))
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/webp"


def test_only_admins_set_the_office_and_only_precisely(guarded: TestClient, people) -> None:
    sign_in(guarded, *people["user"])
    place = {**OFFICE_PLACE, "accuracy": 15}
    assert guarded.put("/api/settings/office-location", json=place).status_code == 403
    sign_in(guarded, *ADMIN)
    rough = {**place, "accuracy": 400}
    assert guarded.put("/api/settings/office-location", json=rough).status_code == 422
    body = guarded.put("/api/settings/office-location", json=place).json()
    assert body["values"]["office_location"] == OFFICE_PLACE
    body = guarded.delete("/api/settings/office-location").json()
    assert body["values"]["office_location"] is None
