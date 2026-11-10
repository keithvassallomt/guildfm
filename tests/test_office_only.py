"""Through Cloudflare, only visitors from the office's own public address get in; everyone
else is told to join the office Wi-Fi. Requests that don't come through Cloudflare, like the
speakers', are left alone. The office's address can change, so GuildFM looks again."""

import asyncio
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from guildfm import office as office_module
from guildfm.main import create_app
from guildfm.office import Office

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
