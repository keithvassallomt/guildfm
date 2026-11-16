"""The named fields in a talk station's script prompt, and what's behind each."""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from guildfm.fields import material, used
from guildfm.models import (
    DJProfile,
    Lineup,
    LineupSlot,
    Playlist,
    PlaylistKind,
    SourceState,
    Station,
)
from tests.fakes import FakeOpenAI

# Tuesday 13 October 2026, at lunchtime in the office.
LUNCHTIME = datetime(2026, 10, 13, 12, 30)
WHERE = "Carlisle, Cumbria, UK"


def test_a_prompt_names_its_fields() -> None:
    prompt = "Chat about [News], the [weather] and [this], then [lineup] and [news] again."
    assert used(prompt) == ["news", "weather", "lineup"]
    assert used("Just chat.") == []


async def _station(sessionmaker, prompt: str) -> int:
    """A talk station with Guildbert and Debbie, and Della hosting another station."""
    async with sessionmaker() as db:
        guildbert = DJProfile(name="Guildbert", personality="Cheeky.", voice="cedar", created_at=0)
        debbie = DJProfile(name="Debbie", personality="Bubbly.", voice="cedar", created_at=0)
        della = DJProfile(
            name="Della",
            personality="Warm and upbeat.",
            voice="marin",
            pet_peeves="Songs that fade out.",
            obsession="Her sourdough starter.",
            created_at=0,
        )
        talk = Station(
            name="The Lunch Break",
            description="Soul.",
            talk_station=True,
            script_prompt=prompt,
            created_at=0,
        )
        talk.set_hosts([guildbert, debbie])
        friday = Station(name="Friday Feeling", description="Disco.", created_at=0)
        friday.set_hosts([della])
        db.add_all([talk, friday])
        await db.commit()
        return talk.id


async def _material(sessionmaker, awareness, station_id: int, now: datetime, wait: float = 0):
    async with sessionmaker() as db:
        station = await db.get(Station, station_id)
        return await material(db, awareness, station, WHERE, now, wait)


def web_searches(openai: FakeOpenAI) -> list[str]:
    return [body["input"] for body in openai.asked if body.get("tools")]


def test_only_the_fields_a_prompt_uses_are_looked_up(
    client: TestClient, openai: FakeOpenAI
) -> None:
    openai.found = {
        # The web search cites its sources, though it's asked not to; they're taken out.
        "light news": "- 12 Oct: A goat was elected mayor of a Cumbrian village. "
        "([cumbria.example](https://cumbria.example/goat?utm_source=openai))",
        "British football": "- 12 Oct: [Carlisle United](https://example.com) won 3-0.",
    }
    sessions, awareness = client.app.state.sessionmaker, client.app.state.awareness
    talk = client.portal.call(_station, sessions, "Chat about [news], [sports] and [weather].")

    found = client.portal.call(_material, sessions, awareness, talk, LUNCHTIME, 5)
    assert found == {
        "news": "- 12 Oct: A goat was elected mayor of a Cumbrian village.",
        "weather": f"Right now in {WHERE}: light rain, 9°C, feels like 7°C, wind 14 km/h, "
        "daylight.",
        "sports": "- 12 Oct: Carlisle United won 3-0.",
    }
    searches = web_searches(openai)
    assert len(searches) == 2  # no celebrities, and no music news
    assert any("politics" in search for search in searches)  # kept out of the light news

    # Kept, so asking again looks nothing up.
    client.portal.call(_material, sessions, awareness, talk, LUNCHTIME)
    assert len(web_searches(openai)) == 2


def test_birthdays_are_only_good_on_the_day(client: TestClient, openai: FakeOpenAI) -> None:
    openai.found = {"birthday": "- Born 13 October 1959: a famous singer."}
    sessions, awareness = client.app.state.sessionmaker, client.app.state.awareness
    talk = client.portal.call(_station, sessions, "Any [celebrities] about?")

    found = client.portal.call(_material, sessions, awareness, talk, LUNCHTIME, 5)
    assert found == {"celebrities": "- Born 13 October 1959: a famous singer."}
    assert "Today is Tuesday 13 October 2026." in web_searches(openai)[0]

    # The next day, yesterday's birthdays are no use: they're looked up again for today.
    tomorrow = LUNCHTIME + timedelta(days=1)
    assert client.portal.call(_material, sessions, awareness, talk, tomorrow) == {}
    client.portal.call(awareness.settle)
    assert "Today is Wednesday 14 October 2026." in web_searches(openai)[1]
    assert client.portal.call(_material, sessions, awareness, talk, tomorrow) != {}


async def _lineup_on(sessionmaker, station_id: int) -> None:
    """A line-up on: a morning show, the talk show at lunchtime, then a playlist and a show."""
    async with sessionmaker() as db:
        mornings = Station(name="Mornings", description="Pop.", created_at=0)
        coffee = Playlist(name="Coffee Break", kind=PlaylistKind.CUSTOM, created_at=0)
        teatime = Station(name="Teatime", description="Jazz.", created_at=0)
        day = Lineup(name="Office Day", created_at=0)
        day.slots = [
            LineupSlot(start=8 * 60, end=12 * 60, station=mornings),
            LineupSlot(start=12 * 60, end=13 * 60, station_id=station_id),
            LineupSlot(start=13 * 60, end=15 * 60, playlist=coffee),
            LineupSlot(start=15 * 60, end=17 * 60, station=teatime),
        ]
        db.add_all([mornings, coffee, teatime, day])
        await db.flush()
        source = await db.get(SourceState, 1) or SourceState(id=1)
        source.station_id, source.lineup_id = station_id, day.id
        db.add(source)
        await db.commit()


def test_lineup_is_the_rest_of_the_day(client: TestClient) -> None:
    sessions, awareness = client.app.state.sessionmaker, client.app.state.awareness
    talk = client.portal.call(_station, sessions, "What's on later? [lineup]")
    found = client.portal.call(_material, sessions, awareness, talk, LUNCHTIME)
    assert found == {"lineup": "No line-up is on today."}

    client.portal.call(_lineup_on, sessions, talk)
    found = client.portal.call(_material, sessions, awareness, talk, LUNCHTIME)
    assert found["lineup"] == (
        "The rest of today's line-up, Office Day:\n"
        "- 12:00 to 13:00: The Lunch Break, a talk show, with Guildbert and Debbie\n"
        "- 13:00 to 15:00: the playlist Coffee Break\n"
        "- 15:00 to 17:00: Teatime, a show"
    )


def test_djs_are_the_other_djs(client: TestClient) -> None:
    sessions, awareness = client.app.state.sessionmaker, client.app.state.awareness
    talk = client.portal.call(_station, sessions, "Have a go at the other [DJs].")
    found = client.portal.call(_material, sessions, awareness, talk, LUNCHTIME)
    # Not Guildbert or Debbie, who are on this station.
    assert found == {
        "djs": "GuildFM's other DJs:\n- Della. Warm and upbeat. Hosts Friday Feeling. "
        "Pet peeves: Songs that fade out. Keeps coming back to: Her sourdough starter."
    }
