from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from guildfm.prefs import DEFAULTS
from guildfm.schedule import is_open, next_change
from tests.fakes import spotify_id
from tests.helpers import ADMIN, sign_in

LONDON = ZoneInfo("Europe/London")
WEEKDAYS = DEFAULTS["schedule"]


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """A time in October 2026, in London. Day 12 is a Monday."""
    return datetime(2026, 10, day, hour, minute, tzinfo=LONDON)


# The rules


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (at(13, 7, 59), False),
        (at(13, 8, 0), True),
        (at(13, 17, 59), True),
        (at(13, 18, 0), False),
        (at(17, 12, 0), False),  # Saturday
    ],
)
def test_is_open(moment: datetime, expected: bool) -> None:
    assert is_open(WEEKDAYS, moment) is expected


def test_next_change() -> None:
    assert next_change(WEEKDAYS, at(13, 9, 0)) == at(13, 18, 0)
    assert next_change(WEEKDAYS, at(13, 19, 0)) == at(14, 8, 0)
    # Friday evening: next opening is Monday.
    assert next_change(WEEKDAYS, at(16, 19, 0)) == at(19, 8, 0)
    never = {day: {**hours, "on": False} for day, hours in WEEKDAYS.items()}
    assert next_change(never, at(13, 9, 0)) is None


# Opening and closing


def request(client: TestClient, name: str) -> None:
    client.post("/api/queue", json={"track_id": spotify_id(name)}).raise_for_status()


def tick(client: TestClient) -> None:
    client.portal.call(client.app.state.schedule.tick)


def status(client: TestClient) -> str:
    return client.get("/api/playback").json()["status"]


@pytest.fixture
def evening(client: TestClient, clock) -> None:
    """The app was started after closing time on Tuesday."""
    clock.now = datetime(2026, 10, 13, 19, 0, tzinfo=LONDON)
    tick(client)


def test_starting_up_doesnt_take_the_speakers_over(client: TestClient) -> None:
    sign_in(client, *ADMIN)
    request(client, "fm1")
    tick(client)
    assert status(client) == "stopped"


def test_opening_time_starts_the_queue(client: TestClient, clock, evening, speakers) -> None:
    sign_in(client, *ADMIN)
    request(client, "fm1")
    clock.now = at(14, 8, 0)
    tick(client)
    assert status(client) == "playing"
    assert spotify_id("fm1") in speakers.took_over[-1][0].uri


def test_opening_with_nothing_to_play_starts_at_the_first_request(client, clock, evening):
    sign_in(client, *ADMIN)
    clock.now = at(14, 8, 0)
    tick(client)
    assert status(client) == "stopped"
    request(client, "fm1")
    assert status(client) == "playing"


def test_closing_time_stops_everything(client: TestClient, clock, speakers) -> None:
    sign_in(client, *ADMIN)
    request(client, "fm1")
    client.post("/api/playback/play").raise_for_status()
    clock.now = at(13, 18, 0)
    tick(client)
    assert status(client) == "stopped"
    assert speakers.transport == "PAUSED_PLAYBACK"


def test_an_admins_play_overrides_the_hours(client: TestClient, clock, evening) -> None:
    sign_in(client, *ADMIN)
    request(client, "fm1")
    assert client.post("/api/playback/play").json()["status"] == "playing"
    # It carries on through the next opening time, and stops at the next closing.
    clock.now = at(14, 8, 0)
    tick(client)
    assert status(client) == "playing"
    clock.now = at(14, 18, 0)
    tick(client)
    assert status(client) == "stopped"


def test_a_stop_lasts_until_the_next_opening(client: TestClient, clock, evening) -> None:
    sign_in(client, *ADMIN)
    request(client, "fm1")
    clock.now = at(14, 8, 0)
    tick(client)
    client.post("/api/playback/stop").raise_for_status()
    request(client, "fm2")  # a new request doesn't undo the Stop
    clock.now = at(14, 12, 0)
    tick(client)
    assert status(client) == "stopped"

    clock.now = at(14, 18, 0)
    tick(client)
    clock.now = at(15, 8, 0)
    tick(client)
    assert status(client) == "playing"


def test_screens_are_told_the_hours(client: TestClient, clock) -> None:
    sign_in(client, *ADMIN)
    tick(client)
    hours = client.get("/api/playback").json()["hours"]
    assert hours["open"] is True
    assert datetime.fromisoformat(hours["next_change"]) == at(13, 18, 0)


def test_changing_the_hours_applies_straight_away(client: TestClient, clock, speakers) -> None:
    sign_in(client, *ADMIN)
    request(client, "fm1")
    client.post("/api/playback/play").raise_for_status()
    tick(client)
    week = {day: {"on": False, "start": "08:00", "end": "18:00"} for day in WEEKDAYS}
    client.patch("/api/settings", json={"schedule": week}).raise_for_status()
    assert status(client) == "stopped"
    assert client.get("/api/playback").json()["hours"] == {"open": False, "next_change": None}


def test_times_follow_the_time_zone_setting(client: TestClient, clock) -> None:
    sign_in(client, *ADMIN)
    # 07:30 in London is 08:30 in Malta.
    clock.now = datetime(2026, 10, 13, 7, 30, tzinfo=LONDON).astimezone(UTC)
    assert client.portal.call(client.app.state.schedule.open_now) is False
    client.patch("/api/settings", json={"timezone": "Europe/Malta"}).raise_for_status()
    assert client.portal.call(client.app.state.schedule.open_now) is True
