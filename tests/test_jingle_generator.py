import time
import zipfile
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from guildfm.backups import back_up
from guildfm.models import DraftStatus, JingleDraft
from guildfm.speech import fit, sang
from tests.fakes import FakeElevenLabs, FakeOpenAI, mp3
from tests.helpers import ADMIN, sign_in

ABOUT = "GuildFM is the office radio for a team of map makers in Carlisle."


@pytest.fixture(autouse=True)
def waits(client: TestClient) -> list[float]:
    """The seconds GuildFM waits for a busy ElevenLabs, which pass at once here."""
    waited = []

    async def wait(seconds: float) -> None:
        waited.append(seconds)

    client.app.state.speech.sleep = wait
    return waited


def make_station(client: TestClient, **fields) -> dict:
    body = {"name": "Guildbert's Hour", "description": "Upbeat soul.", **fields}
    response = client.post("/api/stations", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def draft(client: TestClient, prompt: str = "A bright synth sting.", **fields) -> dict:
    body = {"name": "Sting", "prompt": prompt, "length": 8, **fields}
    response = client.post("/api/jingles/drafts", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def made(client: TestClient, station_id: int | None = None) -> list[dict]:
    """The round, once ElevenLabs has made everything in it."""
    client.portal.call(client.app.state.composer.settle)
    return round_of(client, station_id)["drafts"]


def round_of(client: TestClient, station_id: int | None = None) -> dict:
    params = {"station_id": station_id} if station_id else {}
    response = client.get("/api/jingles/drafts", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def decide(client: TestClient, draft_id: int, **change) -> dict:
    response = client.patch(f"/api/jingles/drafts/{draft_id}", json=change)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_ai_writes_system_idents_from_about_guildfm(client, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    assert client.get("/api/settings").json()["values"]["about"].startswith("GuildFM is")
    client.patch("/api/settings", json={"about": f"  {ABOUT}  "}).raise_for_status()
    assert client.get("/api/settings").json()["values"]["about"] == ABOUT

    cards = [
        {},
        {"text": "Soft piano for the afternoon."},
        {"text": "A brass hit.", "instrumental": True},
    ]
    response = client.post("/api/jingles/ideas", json={"cards": cards, "write": [0, 1]})
    assert response.status_code == 200, response.text
    assert response.json() == [
        {"name": "Idea 1", "prompt": "Bright sting number 1.", "seconds": 7},
        {"name": "Idea 2", "prompt": "Bright sting number 2.", "seconds": 8},
    ]

    asked = openai.asked_for("jingle_ideas")[0]
    assert "Never name a real artist" in asked["instructions"]
    # Words, always, and sung: the music model leaves spoken lines out.
    assert "Every jingle has words" in asked["instructions"]
    assert "never spoken" in asked["instructions"]
    jingle = asked["text"]["format"]["schema"]["properties"]["jingles"]["items"]
    assert "instrumental" not in jingle["properties"]
    assert "system idents for GuildFM, the office radio that every AI station" in asked["input"]
    assert f"What GuildFM is, in its admins' words: {ABOUT}" in asked["input"]
    assert "1. Write this one.\n" in asked["input"]
    assert "2. Write this one, building on what's there" in asked["input"]
    assert "Soft piano for the afternoon." in asked["input"]
    assert "3. Written already, an instrumental with no words: A brass hit." in asked["input"]
    assert "Made before" not in asked["input"]


def test_the_ai_writes_from_the_station_in_its_editor(client, openai: FakeOpenAI, people) -> None:
    sign_in(client, *people["curator"])
    station = make_station(client, dj=True, dj_name="Guildbert", personality="Warm and dry.")
    client.post(
        "/api/jingles/ideas", json={"station_id": station["id"], "cards": [{}], "write": [0]}
    ).raise_for_status()
    saved = openai.asked_for("jingle_ideas")[-1]["input"]
    assert 'station idents for "Guildbert\'s Hour"' in saved
    assert "What it plays: Upbeat soul." in saved
    assert "Its DJ is Guildbert. Warm and dry." in saved
    assert "GuildFM is the office radio. Everyone" not in saved

    # Unsaved changes in the editor count.
    editing = {"name": "Soul Kitchen", "description": "Deep funk.", "dj_name": "Guildbert"}
    client.post(
        "/api/jingles/ideas",
        json={"station_id": station["id"], "station": editing, "cards": [{}], "write": [0]},
    ).raise_for_status()
    unsaved = openai.asked_for("jingle_ideas")[-1]["input"]
    assert 'station idents for "Soul Kitchen"' in unsaved
    assert "What it plays: Deep funk." in unsaved
    assert "Its DJ is Guildbert.\n" in unsaved


def test_the_ai_writes_an_instrumental_only_when_asked(client, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    body = {"cards": [{"instrumental": True}, {"text": "Brass.", "instrumental": True}]}
    client.post("/api/jingles/ideas", json=body | {"write": [0, 1]}).raise_for_status()
    asked = openai.asked_for("jingle_ideas")[-1]["input"]
    assert "1. Write this one, an instrumental with no words.\n" in asked
    assert "2. Write this one, an instrumental with no words, building on" in asked


def test_the_ai_writing_too_few_or_failing(client, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    openai.ideas = openai.ideas[:1]
    response = client.post("/api/jingles/ideas", json={"cards": [{}, {}], "write": [0, 1]})
    assert response.status_code == 502
    assert "didn't write them all" in response.json()["detail"]
    openai.down = True
    response = client.post("/api/jingles/ideas", json={"cards": [{}], "write": [0]})
    assert response.status_code == 502
    bad = client.post("/api/jingles/ideas", json={"cards": [{}], "write": [1]})
    assert bad.status_code == 422


def test_drafts_are_made_then_kept_or_turned_down(client, elevenlabs: FakeElevenLabs) -> None:
    sign_in(client, *ADMIN)
    first = draft(client, "A bright synth sting.", length=6)
    assert first["status"] == "making"
    second = draft(client, "Soft piano.", name="Piano", length=12, instrumental=True)
    third = draft(client, "A brass hit.", name="Brass")

    drafts = made(client)
    assert [d["status"] for d in drafts] == ["ready"] * 3
    assert [d["seconds"] for d in drafts] == [6, 12, 8]
    assert client.get(drafts[0]["url"]).content == mp3(6)

    # Keeping one makes it a jingle at once; undoing takes it back out.
    kept = decide(client, first["id"], status="kept")
    assert kept["status"] == "kept"
    [jingle] = client.get("/api/jingles").json()
    assert (jingle["name"], kept["url"]) == ("Sting", jingle["url"])
    assert client.get(jingle["url"]).content == mp3(6)
    undone = decide(client, first["id"], status="ready")
    assert client.get("/api/jingles").json() == []
    assert client.get(undone["url"]).content == mp3(6)
    decide(client, first["id"], status="kept", name="Morning sparkle")
    assert [j["name"] for j in client.get("/api/jingles").json()] == ["Morning sparkle"]
    decide(client, first["id"], name="Sparkle")
    assert [j["name"] for j in client.get("/api/jingles").json()] == ["Sparkle"]

    turned = decide(client, second["id"], status="turned_down")
    assert turned["status"] == "turned_down"
    assert client.get(turned["url"]).status_code == 200  # still there, to undo
    refused = client.patch(f"/api/jingles/drafts/{second['id']}", json={"status": "kept"})
    assert refused.status_code == 409

    # Done: the kept one stays, the turned down one is remembered, and the undecided one goes.
    client.post("/api/jingles/drafts/done").raise_for_status()
    assert round_of(client)["drafts"] == []
    assert [j["name"] for j in client.get("/api/jingles").json()] == ["Sparkle"]
    assert client.get(turned["url"]).status_code == 404
    assert client.get(drafts[2]["url"]).status_code == 404
    assert third["id"] not in [d["id"] for d in round_of(client)["drafts"]]


def test_the_ai_knows_what_was_kept_and_turned_down(client, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    keep = draft(client, "A bright synth sting.", length=6)
    turn = draft(client, "A kazoo solo.")
    made(client)
    decide(client, keep["id"], status="kept")
    decide(client, turn["id"], status="turned_down")
    client.post("/api/jingles/drafts/done").raise_for_status()

    assert (round_of(client)["kept"], round_of(client)["turned_down"]) == (1, 1)
    client.post("/api/jingles/ideas", json={"cards": [{}], "write": [0]}).raise_for_status()
    asked = openai.asked_for("jingle_ideas")[-1]["input"]
    assert "Made before and kept" in asked
    assert "- A bright synth sting. (6 seconds)" in asked
    assert "turned down, because people didn't like how they came out" in asked
    assert "- A kazoo solo." in asked

    # A station's own are kept apart from the system idents.
    station = make_station(client)
    client.post(
        "/api/jingles/ideas", json={"station_id": station["id"], "cards": [{}], "write": [0]}
    ).raise_for_status()
    assert "kazoo" not in openai.asked_for("jingle_ideas")[-1]["input"]


def test_a_refused_description_comes_back_to_change(client, elevenlabs: FakeElevenLabs) -> None:
    sign_in(client, *ADMIN)
    elevenlabs.music_status = 400
    elevenlabs.music_detail = {
        "status": "bad_prompt",
        "message": "Prompt contains copyrighted material.",
        "data": {"prompt_suggestion": "Late-90s boy band pop harmonies."},
    }
    first = draft(client, "Sounds like the Backstreet Boys.")
    [failed] = made(client)
    assert failed["status"] == "failed"
    assert "names a real artist" in failed["problem"]
    assert failed["suggestion"] == "Late-90s boy band pop harmonies."
    assert failed["url"] is None
    assert client.app.state.speech.eleven_health.state == "failing"

    elevenlabs.music_status = 200
    response = client.post(
        f"/api/jingles/drafts/{first['id']}/again", json={"prompt": failed["suggestion"]}
    )
    assert response.json()["status"] == "making"
    [ready] = made(client)
    assert (ready["status"], ready["prompt"]) == ("ready", "Late-90s boy band pop harmonies.")
    assert (ready["problem"], ready["suggestion"]) == (None, None)
    assert elevenlabs.plans[-1]["prompt"] == "Late-90s boy band pop harmonies."

    # Trying again with the same description makes a new take.
    old_url = ready["url"]
    client.post(f"/api/jingles/drafts/{first['id']}/again").raise_for_status()
    [again] = made(client)
    assert again["url"] != old_url
    assert client.get(old_url).status_code == 404


@pytest.mark.parametrize(
    ("status", "detail", "problem"),
    [
        (401, {"status": "quota_exceeded"}, "out of credits"),
        (401, {"status": "missing_permissions"}, "isn't allowed to make music"),
        (402, {}, "plan doesn't include music"),
        (429, {}, "busy making other music"),
        (500, {}, "couldn't make that one"),
    ],
)
def test_elevenlabs_problems_show_on_the_draft(
    client, elevenlabs: FakeElevenLabs, status, detail, problem
) -> None:
    sign_in(client, *ADMIN)
    elevenlabs.music_status, elevenlabs.music_detail = status, detail
    created = draft(client)
    [failed] = made(client)
    assert failed["status"] == "failed"
    assert problem in failed["problem"]
    # One that failed can be left out.
    client.delete(f"/api/jingles/drafts/{created['id']}").raise_for_status()
    assert round_of(client)["drafts"] == []


def test_a_round_holds_six(client) -> None:
    sign_in(client, *ADMIN)
    for _ in range(6):
        draft(client)
    response = client.post(
        "/api/jingles/drafts", json={"name": "Seventh", "prompt": "One more.", "length": 8}
    )
    assert response.status_code == 409
    long = client.post("/api/jingles/drafts", json={"name": "Long", "prompt": "x", "length": 16})
    assert long.status_code == 422


def test_no_drafts_without_elevenlabs(client) -> None:
    sign_in(client, *ADMIN)
    client.app.state.speech._eleven_key = ""
    response = client.post(
        "/api/jingles/drafts", json={"name": "Sting", "prompt": "A sting.", "length": 8}
    )
    assert response.status_code == 409
    assert "ELEVENLABS_API_KEY" in response.json()["detail"]


def test_the_jingle_lists_permissions_apply(client, people) -> None:
    sign_in(client, *ADMIN)
    system = draft(client)
    sign_in(client, *people["curator"])
    station = make_station(client)
    own = draft(client, station_id=station["id"])
    assert own["station_id"] == station["id"]
    assert len(made(client, station["id"])) == 1
    # System idents are for admins.
    assert client.get("/api/jingles/drafts").status_code == 403
    assert client.post("/api/jingles/ideas", json={"cards": [{}], "write": [0]}).status_code == 403
    assert (
        client.patch(f"/api/jingles/drafts/{system['id']}", json={"name": "X"}).status_code == 403
    )
    # Keeping one makes a station ident.
    decide(client, own["id"], status="kept")
    [jingle] = client.get("/api/jingles", params={"station_id": station["id"]}).json()
    assert jingle["kind"] == "station"

    sign_in(client, *people["user"])
    assert (
        client.get("/api/jingles/drafts", params={"station_id": station["id"]}).status_code == 403
    )

    sign_in(client, *ADMIN)
    ai_picks = next(s for s in client.get("/api/stations").json() if s["kind"] == "ai_picks")
    refused = client.post(
        "/api/jingles/drafts",
        json={"station_id": ai_picks["id"], "name": "X", "prompt": "A sting.", "length": 8},
    )
    assert refused.status_code == 409


def test_deleting_a_station_deletes_its_drafts(client) -> None:
    sign_in(client, *ADMIN)
    station = make_station(client)
    draft(client, station_id=station["id"])
    [ready] = made(client, station["id"])
    client.delete(f"/api/stations/{station['id']}").raise_for_status()
    assert client.get(ready["url"]).status_code == 404


def test_rounds_nobody_finished_are_done_with_after_a_day(client, openai: FakeOpenAI) -> None:
    sign_in(client, *ADMIN)
    keep, turn, left = draft(client), draft(client, "A kazoo solo."), draft(client)
    drafts = made(client)
    decide(client, keep["id"], status="kept")
    decide(client, turn["id"], status="turned_down")

    composer = client.app.state.composer
    client.portal.call(composer.clear_old, time.time() + 60)
    assert len(round_of(client)["drafts"]) == 3  # not a day old yet
    client.portal.call(composer.clear_old, time.time() + 25 * 60 * 60)
    assert round_of(client)["drafts"] == []
    assert len(client.get("/api/jingles").json()) == 1
    assert client.get(drafts[2]["url"]).status_code == 404
    client.post("/api/jingles/ideas", json={"cards": [{}], "write": [0]}).raise_for_status()
    assert "- A kazoo solo." in openai.asked_for("jingle_ideas")[-1]["input"]
    assert left["id"] not in [d["id"] for d in round_of(client)["drafts"]]


def test_a_restart_fails_drafts_being_made(start) -> None:
    with start() as client:
        sign_in(client, *ADMIN)
        created = draft(client)
        made(client)

        async def unfinished() -> None:
            async with client.app.state.sessionmaker() as db:
                row = await db.get(JingleDraft, created["id"])
                row.status, row.file = DraftStatus.MAKING, None
                await db.commit()

        client.portal.call(unfinished)
    with start() as client:
        sign_in(client, *ADMIN)
        [failed] = round_of(client)["drafts"]
        assert failed["status"] == "failed"
        assert "restarted" in failed["problem"]


def test_drafts_are_left_out_of_backups(client, settings) -> None:
    sign_in(client, *ADMIN)
    keep = draft(client)
    draft(client)
    made(client)
    decide(client, keep["id"], status="kept")
    path = back_up(settings.data_dir, settings.backups, datetime(2026, 10, 21, 12, 0))
    names = zipfile.ZipFile(path).namelist()
    assert any(name.startswith("media/jingles/") for name in names)
    assert not any("jingle-drafts" in name for name in names)


def test_jingles_come_out_the_length_asked_for(client, elevenlabs: FakeElevenLabs) -> None:
    """ElevenLabs plans each one, then makes it from the plan fitted to the length: made from a
    description alone, it runs over."""
    sign_in(client, *ADMIN)
    draft(client, "Cheeky funk.", length=6)
    [ready] = made(client)
    assert elevenlabs.plans == [
        {"prompt": "Cheeky funk.", "music_length_ms": 6000, "model_id": "music_v2_5"}
    ]
    [made_from] = elevenlabs.music
    assert made_from["model_id"] == "music_v2_5"
    assert "prompt" not in made_from
    chunks = made_from["composition_plan"]["chunks"]
    # Planned at 3 and 4 seconds; fitted to 6, with 3 seconds at least in each part.
    assert [chunk["duration_ms"] for chunk in chunks] == [3000, 3000]
    assert chunks[1] == {
        "text": "[Tag]\nGuild F M!",
        "duration_ms": 3000,
        "positive_styles": ["funk", "group vocals"],
        "negative_styles": [],
        "context_adherence": "high",
    }
    assert ready["seconds"] == 6


def test_a_short_jingle_has_its_parts_joined() -> None:
    planned = [
        {"text": "[Intro]", "duration_ms": 3000, "positive_styles": ["funk"]},
        {"text": "[Hook]\nGuild F M!", "duration_ms": 4000, "positive_styles": ["funk", "choir"]},
        {"text": "[Stop]", "duration_ms": 3000, "positive_styles": ["drum stop"]},
    ]
    [one] = fit(planned, 5000)
    assert one["text"] == "[Intro]\n[Hook]\nGuild F M!\n[Stop]"
    assert one["positive_styles"] == ["funk", "choir", "drum stop"]
    assert one["duration_ms"] == 5000
    two = fit(planned, 7000)
    assert [part["duration_ms"] for part in two] == [3000, 4000]
    longer = fit(planned, 15000)
    assert [part["duration_ms"] for part in longer] == [3000, 9000, 3000]


def test_an_instrumental_has_its_words_taken_out(client, elevenlabs: FakeElevenLabs) -> None:
    sign_in(client, *ADMIN)
    draft(client, "Soft piano.", length=12, instrumental=True)
    made(client)
    assert elevenlabs.plans[0]["prompt"] == "Soft piano. Instrumental only: no vocals."
    chunks = elevenlabs.music[0]["composition_plan"]["chunks"]
    assert [chunk["text"] for chunk in chunks] == ["[Intro]\n{tap}", "[Tag]"]
    assert chunks[1]["positive_styles"] == ["funk", "instrumental"]
    assert chunks[1]["negative_styles"] == ["vocals", "singing", "spoken word"]
    assert sum(chunk["duration_ms"] for chunk in chunks) == 12000


def test_a_busy_elevenlabs_is_asked_again(client, elevenlabs, waits) -> None:
    sign_in(client, *ADMIN)
    elevenlabs.busy_for = 2
    draft(client)
    [ready] = made(client)
    assert ready["status"] == "ready"
    assert waits == [5, 15]

    elevenlabs.busy_for = 4
    again = draft(client)
    failed = next(d for d in made(client) if d["id"] == again["id"])
    assert failed["status"] == "failed"
    assert "busy making other music" in failed["problem"]
    assert waits == [5, 15, 5, 15, 30]


def test_the_words_are_kept_to_the_ones_quoted(client, elevenlabs: FakeElevenLabs) -> None:
    """ElevenLabs' plans add lines of their own."""
    sign_in(client, *ADMIN)
    elevenlabs.parts = [
        ("[Intro]\n{guitar pickup}", 3),
        ("[Hook]\nFrom desk to desk, Guild F M\nWe keep it simple, keep it moving\n(ooh)", 7),
    ]
    draft(client, 'Folk; sing "From desk to desk, Guild F M" in harmony.', length=10)
    made(client)
    chunks = elevenlabs.music[0]["composition_plan"]["chunks"]
    assert [chunk["text"] for chunk in chunks] == [
        "[Intro]\n{guitar pickup}",
        "[Hook]\nFrom desk to desk, Guild F M\n(ooh)",
    ]


def test_quoted_words_go_in_when_the_plan_has_none_of_them() -> None:
    plan = [
        {"text": "[Intro]", "duration_ms": 3000, "positive_styles": ["folk"]},
        {"text": "[Hook]\nSomething else entirely", "duration_ms": 6000},
    ]
    parts = fit(plan, 9000, words=["From desk to desk, Guild F M"])
    assert [part["text"] for part in parts] == ["[Intro]", "[Hook]\nFrom desk to desk, Guild F M"]
    wordless = [{"text": "[Intro]", "duration_ms": 3000}, {"text": "{strum}", "duration_ms": 6000}]
    parts = fit(wordless, 9000, words=["Guild F M"])
    assert [part["text"] for part in parts] == ["[Intro]", "Guild F M\n{strum}"]


def test_the_voices_set_the_tone_from_the_first_part() -> None:
    """ElevenLabs takes its tone from the first part's styles; a wordless intro without voices
    in them sometimes left the words unsung."""
    plan = [
        {"text": "[Intro]\n{pickup}", "duration_ms": 3000,
         "positive_styles": ["folk", "rising strings"]},
        {"text": "[Hook]\nGuild F M", "duration_ms": 6000,
         "positive_styles": ["folk", "loose two-part harmony", "intimate male vocal"]},
    ]  # fmt: skip
    first = fit(plan, 9000)[0]["positive_styles"]
    assert first == ["folk", "rising strings", "loose two-part harmony", "intimate male vocal"]
    plan[1]["positive_styles"] = ["folk"]
    assert fit(plan, 9000)[0]["positive_styles"][-1] == "lead vocals"
    # Not for an instrumental, or a plan with no words.
    assert "lead vocals" not in fit(plan, 9000, instrumental=True)[0]["positive_styles"]
    plan[1]["text"] = "[Hook]"
    assert fit(plan, 9000)[0]["positive_styles"] == ["folk", "rising strings"]


def test_hearing_the_words() -> None:
    words = "From desk to desk, Guild F M"
    assert sang("From desk to desk, GildFM. Keep it simple.", words)
    assert sang("Gild FM", "Guild F M")
    assert not sang("\U0001f3b6", words)
    assert not sang("", words)
    assert not sang("Ooh.", "(ooh)\nGuild F M")


def test_a_jingle_without_its_words_is_made_again(client, openai, elevenlabs) -> None:
    sign_in(client, *ADMIN)
    openai.heard = ["\U0001f3b6", "Guild F M!"]
    draft(client)
    [ready] = made(client)
    assert (ready["status"], ready["problem"]) == ("ready", None)
    assert (len(elevenlabs.music), openai.listened) == (2, 2)


def test_a_jingle_without_its_words_twice_says_so(client, openai, elevenlabs) -> None:
    sign_in(client, *ADMIN)
    openai.heard = ["\U0001f3b6"]
    created = draft(client)
    [ready] = made(client)
    assert ready["status"] == "ready"
    assert "words didn't come through" in ready["problem"]
    assert len(elevenlabs.music) == 2
    # Trying again starts afresh.
    openai.heard = ["Guild F M!"]
    client.post(f"/api/jingles/drafts/{created['id']}/again").raise_for_status()
    [again] = made(client)
    assert again["problem"] is None


def test_no_listening_for_an_instrumental_or_when_openai_cant(client, openai, elevenlabs) -> None:
    sign_in(client, *ADMIN)
    draft(client, instrumental=True)
    made(client)
    assert openai.listened == 0
    openai.hearing_down = True
    draft(client)
    assert all(d["status"] == "ready" and d["problem"] is None for d in made(client))
    assert len(elevenlabs.music) == 2  # one each: none made again
