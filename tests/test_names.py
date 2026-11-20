"""Names people pick for themselves are checked: nothing vulgar, and something that reads like
a name. A username only has to be clean. When OpenAI can't say, the name goes through."""

from fastapi.testclient import TestClient

from tests.fakes import FakeOpenAI
from tests.helpers import PASSWORD, register


def sign_up(client: TestClient, username: str, display_name: str):
    client.cookies.clear()
    return client.post(
        "/api/auth/register",
        json={"username": username, "display_name": display_name, "password": PASSWORD},
    )


def test_a_vulgar_name_is_turned_down(client: TestClient, openai: FakeOpenAI) -> None:
    openai.names["BigBalls"] = "vulgar"
    response = sign_up(client, "ricky", "BigBalls")
    assert response.status_code == 422
    assert response.json()["detail"] == "Pick a name you'd be happy for the whole office to see."


def test_a_word_that_isnt_a_name_is_turned_down(client: TestClient, openai: FakeOpenAI) -> None:
    openai.names["bungalistic"] = "not_a_name"
    response = sign_up(client, "tony", "bungalistic")
    assert response.status_code == 422
    assert response.json()["detail"].startswith("That doesn't look like a name.")


def test_a_name_with_a_description_is_turned_down(client: TestClient, openai: FakeOpenAI) -> None:
    openai.names["GARY FROM NOTTIGHAM"] = "described"
    response = sign_up(client, "gary", "GARY FROM NOTTIGHAM")
    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Just your name, please: leave out where you're from or what you do."
    )
    # The AI is told the rule, and can answer with it.
    (asked,) = [a for a in openai.asked_for("name_check") if a["input"] == "GARY FROM NOTTIGHAM"]
    assert '"Gary from Nottingham", "Sam in Accounts"' in asked["instructions"]
    assert "misspellings don't change the answer" in asked["instructions"]
    assert "described" in asked["text"]["format"]["schema"]["properties"]["verdict"]["enum"]


def test_a_username_only_has_to_be_clean(client: TestClient, openai: FakeOpenAI) -> None:
    openai.names["hatkinson101"] = "not_a_name"
    assert sign_up(client, "hatkinson101", "Harry").status_code == 201
    openai.names["garyfromnotts"] = "described"
    assert sign_up(client, "garyfromnotts", "Gary").status_code == 201
    openai.names["fucktard"] = "vulgar"
    response = sign_up(client, "fucktard", "Harry")
    assert response.status_code == 422
    assert "username" in response.json()["detail"]


def test_renaming_yourself_is_checked_too(client: TestClient, openai: FakeOpenAI) -> None:
    register(client, "ricky")
    openai.names["BigBalls"] = "vulgar"
    response = client.patch("/api/me", json={"display_name": "BigBalls"})
    assert response.status_code == 422
    assert client.get("/api/me").json()["display_name"] == "Ricky"
    openai.names["Ricky in Accounts"] = "described"
    described = client.patch("/api/me", json={"display_name": "Ricky in Accounts"})
    assert described.status_code == 422
    assert described.json()["detail"].startswith("Just your name, please")
    assert client.get("/api/me").json()["display_name"] == "Ricky"
    asked = len(openai.asked_for("name_check"))
    # Saving the profile without changing the name doesn't ask again.
    client.patch("/api/me", json={"display_name": "Ricky", "announce_requests": False})
    assert len(openai.asked_for("name_check")) == asked


def test_names_go_through_when_openai_is_down(client: TestClient, openai: FakeOpenAI) -> None:
    openai.down = True
    openai.names["bungalistic"] = "not_a_name"
    assert sign_up(client, "tony", "bungalistic").status_code == 201
