import logging

from fastapi.testclient import TestClient

from guildfm.logs import Recent
from tests.fakes import FakeElevenLabs, FakeOpenAI
from tests.helpers import ADMIN, read_speakers, sign_in


def status(client: TestClient) -> dict:
    response = client.get("/api/status")
    assert response.status_code == 200, response.text
    return response.json()


def services(client: TestClient) -> dict[str, dict]:
    return {service["key"]: service for service in status(client)["services"]}


def test_only_admins_see_the_status(client: TestClient, people) -> None:
    sign_in(client, *people["curator"])
    assert client.get("/api/status").status_code == 403


def test_the_speakers_and_each_service(client: TestClient, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    read_speakers(client)
    found = services(client)
    assert list(found) == ["speakers", "spotify", "openai", "elevenlabs", "weather", "ffmpeg"]
    assert found["speakers"]["state"] == "ok"
    assert found["speakers"]["detail"] == "3 rooms answering. GuildFM is stopped."
    assert found["openai"]["state"] == "unused"
    assert found["ffmpeg"]["state"] == "off"  # the tests turn levelling off
    assert "No account is connected" in found["spotify"]["detail"]

    # Each service shows how its latest call went.
    client.post("/api/announcements/preview", json={"text": "Testing."}).raise_for_status()
    assert services(client)["openai"]["state"] == "ok"
    openai.status = 429
    client.post("/api/announcements/preview", json={"text": "Testing again."})
    found = services(client)["openai"]
    assert found["state"] == "failing"
    assert found["detail"].startswith("OpenAI is busy, or the account is out of credit.")
    assert found["ok_at"] and found["failed_at"]


def test_elevenlabs_credits(client: TestClient, elevenlabs: FakeElevenLabs) -> None:
    sign_in(client, *ADMIN)
    assert status(client)["credits"] == {
        "used": 2235,
        "limit": 131000,
        "resets_at": "2026-11-16T10:30:22Z",
    }


def test_a_key_that_cant_read_the_credits(client: TestClient, elevenlabs: FakeElevenLabs) -> None:
    elevenlabs.subscription = None
    sign_in(client, *ADMIN)
    assert status(client)["credits"] is None
    assert services(client)["elevenlabs"]["state"] == "unused"  # its voices still work


def test_speakers_offline(client: TestClient, speakers) -> None:
    sign_in(client, *ADMIN)
    speakers.available = False
    read_speakers(client)
    found = services(client)["speakers"]
    assert found["state"] == "failing"
    assert found["detail"]


def test_the_latest_problems_from_the_log(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    log = logging.getLogger("guildfm.radio")
    log.warning("The AI couldn't pick songs for a station: nope")
    log.info("Not a problem")
    log.warning("The AI couldn't pick songs for a station: nope")
    problems = status(client)["problems"]
    assert [(p["message"], p["count"], p["level"]) for p in problems] == [
        ("The AI couldn't pick songs for a station: nope", 2, "warning")
    ]


def test_problems_that_come_back_move_to_the_top() -> None:
    recent = Recent(kept=3)
    log = logging.getLogger("guildfm.test_status")
    log.addHandler(recent)
    try:
        log.warning("Weather")
        log.warning("Speakers")
        log.warning("Weather")
        try:
            raise ValueError("bad reply")
        except ValueError:
            log.exception("Picking failed")
    finally:
        log.removeHandler(recent)
    assert [(p.message, p.count, p.level) for p in recent.problems] == [
        ("Picking failed: ValueError: bad reply", 1, "error"),
        ("Weather", 2, "warning"),
        ("Speakers", 1, "warning"),
    ]
