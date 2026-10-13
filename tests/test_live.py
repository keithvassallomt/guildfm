from fastapi.testclient import TestClient


def test_hello_and_ping(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["event"] == "hello"
        assert ws.receive_json() == {"event": "presence", "data": {"connected": 1}}
        ws.send_text("ping")
        assert ws.receive_json()["event"] == "pong"


def test_broadcast_reaches_every_browser(client: TestClient) -> None:
    with client.websocket_connect("/ws") as first:
        first.receive_json()  # hello
        first.receive_json()  # presence: 1
        with client.websocket_connect("/ws") as second:
            assert second.receive_json()["event"] == "hello"
            assert second.receive_json() == {"event": "presence", "data": {"connected": 2}}
            assert first.receive_json() == {"event": "presence", "data": {"connected": 2}}
        assert first.receive_json() == {"event": "presence", "data": {"connected": 1}}
