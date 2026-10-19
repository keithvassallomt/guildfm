import asyncio

import httpx2
import pytest
from fastapi.testclient import TestClient

from guildfm.speech import SpeechClient, SpeechError
from tests.fakes import FakeElevenLabs, FakeOpenAI
from tests.helpers import ADMIN, sign_in
from tests.test_dj import line_up_next, on_air

GUILDBERT = "elevenlabs:guildbert01"


def test_openai_and_elevenlabs_voices_are_offered(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    voices = client.get("/api/voices").json()
    assert "cedar" in voices["openai"]
    assert voices["elevenlabs"] == [
        {"id": "elevenlabs:aurora02", "name": "aurora"},
        {"id": GUILDBERT, "name": "Guildbert"},
    ]
    assert voices["elevenlabs_ready"] is True


def test_an_elevenlabs_announcement_keeps_its_tags(client, openai, elevenlabs) -> None:
    sign_in(client, *ADMIN)
    client.patch("/api/settings", json={"announcement_voice": GUILDBERT}).raise_for_status()
    text = "[excited] Pizza's here! [laughs] Grab a slice."
    response = client.post("/api/announcements/preview", json={"text": text})
    assert response.headers["content-type"] == "audio/mpeg"
    assert elevenlabs.requests == [{"voice": "guildbert01", "text": text, "model_id": "eleven_v4"}]
    assert openai.requests == []


def test_openai_voices_dont_read_tags_out(client: TestClient, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    text = "[excited] Pizza's here in room [3]! [laughs] Grab a slice."
    client.post("/api/announcements/preview", json={"text": text, "voice": "marin"})
    assert openai.requests[0]["input"] == "Pizza's here in room [3]! Grab a slice."


def test_a_dj_with_an_elevenlabs_voice_can_use_tags(client, openai, elevenlabs, speakers) -> None:
    sign_in(client, *ADMIN)
    openai.line = {"script": "[chuckles] Song 1, lovely. Here's Song 2."}
    on_air(client, openai, voice=GUILDBERT)
    line_up_next(client, speakers)
    instructions = openai.asked_for("dj_line")[0]["instructions"]
    assert "audio tag in square brackets" in instructions and "[laughs]" in instructions
    assert elevenlabs.requests[-1]["text"] == "[chuckles] Song 1, lovely. Here's Song 2."
    assert openai.requests == []  # none of it went to OpenAI's voices


def test_a_dj_with_an_openai_voice_is_told_not_to(client, openai: FakeOpenAI, speakers) -> None:
    sign_in(client, *ADMIN)
    on_air(client, openai)  # voice "ash"
    line_up_next(client, speakers)
    instructions = openai.asked_for("dj_line")[0]["instructions"]
    assert "no stage directions" in instructions and "[laughs]" not in instructions


@pytest.mark.parametrize("voice", ["darth", "elevenlabs:", "elevenlabs:not a voice!"])
def test_voices_are_checked(client: TestClient, voice: str) -> None:
    sign_in(client, *ADMIN)
    assert client.patch("/api/settings", json={"announcement_voice": voice}).status_code == 422
    station = {"name": "Grooves", "description": "Soul.", "voice": voice}
    assert client.post("/api/stations", json=station).status_code == 422


def test_elevenlabs_problems_are_explained(client: TestClient, elevenlabs: FakeElevenLabs) -> None:
    sign_in(client, *ADMIN)
    elevenlabs.status = 401
    elevenlabs.detail = {"status": "quota_exceeded", "message": "This request exceeds your quota."}
    body = {"text": "Testing.", "voice": GUILDBERT}
    response = client.post("/api/announcements/preview", json=body)
    assert response.status_code == 502
    assert "out of credits" in response.json()["detail"]

    elevenlabs.status, elevenlabs.detail = 404, {"status": "voice_not_found"}
    response = client.post("/api/announcements/preview", json=body | {"text": "Again."})
    assert "can't find that voice" in response.json()["detail"]


def test_without_a_key_only_openai_voices(tmp_path) -> None:
    def nobody(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("shouldn't ask ElevenLabs without a key")

    async def check() -> None:
        http = httpx2.AsyncClient(transport=httpx2.MockTransport(nobody))
        speech = SpeechClient("test", "gpt-4o-mini-tts", tmp_path, http)
        assert not speech.eleven_ready
        assert await speech.eleven_voices() == []
        with pytest.raises(SpeechError, match="ELEVENLABS_API_KEY"):
            await speech.say("Hello.", GUILDBERT, "")
        await speech.close()

    asyncio.run(check())
