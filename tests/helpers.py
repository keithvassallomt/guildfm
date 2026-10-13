from fastapi.testclient import TestClient

ADMIN = ("admin", "admin-password")
PASSWORD = "password1"


def sign_in(client: TestClient, username: str, password: str = PASSWORD) -> dict:
    """Sign the shared test client in as someone else."""
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def register(client: TestClient, username: str) -> dict:
    client.cookies.clear()
    response = client.post(
        "/api/auth/register",
        json={"username": username, "display_name": username.title(), "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()


def read_speakers(client: TestClient) -> None:
    """Read the (fake) speakers once and let the queue react, as the app does every second."""
    client.portal.call(client.app.state.playback.poll)
    client.portal.call(client.app.state.queue.keep_fed)
