import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from guildfm.live import UNAUTHORISED
from tests.helpers import ADMIN, register, sign_in


def test_live_needs_you_signed_in(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws, pytest.raises(WebSocketDisconnect) as closed:
        ws.receive_json()
    assert closed.value.code == UNAUTHORISED


def test_hello_and_ping(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["event"] == "hello"
        assert ws.receive_json() == {"event": "presence", "data": {"connected": 1}}
        ws.send_text("ping")
        assert ws.receive_json()["event"] == "pong"


@pytest.mark.parametrize(("method", "path"), [("delete", ""), ("post", "/reset-password")])
def test_reset_and_delete_close_live_connections(client: TestClient, method, path) -> None:
    priya = register(client, "priya")
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # hello
        ws.receive_json()  # presence
        sign_in(client, *ADMIN)
        client.request(method, f"/api/users/{priya['id']}{path}").raise_for_status()
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == UNAUTHORISED


def test_broadcast_reaches_every_browser(client: TestClient) -> None:
    register(client, "priya")
    with client.websocket_connect("/ws") as first:
        first.receive_json()  # hello
        first.receive_json()  # presence: 1
        with client.websocket_connect("/ws") as second:
            assert second.receive_json()["event"] == "hello"
            assert second.receive_json() == {"event": "presence", "data": {"connected": 2}}
            assert first.receive_json() == {"event": "presence", "data": {"connected": 2}}
        assert first.receive_json() == {"event": "presence", "data": {"connected": 1}}
