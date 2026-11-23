"""Talk stations: the banter moves, the dice and the show plan."""

import importlib.util
import random
from datetime import date, datetime, timedelta

import pytest

from guildfm.ai import AIClient
from guildfm.db import MIGRATIONS
from guildfm.talk import (
    BITS_SHOWN,
    BY_NAME,
    SHOWS_KEPT,
    TOLD_SHOWN,
    Host,
    deal_bits,
    deal_hooks,
    deal_move,
    link_seconds,
    logged,
    plan_show,
    roll_happening,
    segment_count,
    segment_lengths,
    told_lately,
    with_hooks,
    with_told,
)
from tests.conftest import fake
from tests.fakes import FakeOpenAI


def show(
    on: str,
    topics: list[str] | None = None,
    bits: list[tuple[str, str]] = (),
    hooks: dict[str, list[str]] | None = None,
    told: list[str] | None = None,
) -> dict:
    """A show in a station's log."""
    logged = {
        "on": on,
        "bits": [{"move": move, "idea": idea} for move, idea in bits],
        "topics": topics or [],
        "hooks": hooks or {},
    }
    return logged if told is None else logged | {"told": told}


GUILDBERT = Host("Guildbert", "Cheeky.", pet_peeves="Songs that fade out.")
DEBBIE = Host("Debbie", "Bubbly.", soft_spots="ABBA.")
PLAIN = [Host("Guildbert", "Cheeky."), Host("Debbie", "Bubbly.")]  # no hooks at all
LUNCHTIME = datetime(2026, 11, 16, 12, 0)


def test_talk_takes_its_share_of_the_time() -> None:
    assert link_seconds(50) == 210  # as long as a song
    assert link_seconds(40) == 140
    assert link_seconds(80) == 840  # 14 minutes between songs
    assert link_seconds(100) is None  # no songs: it runs on
    # Two minutes at most, so the first is made while the song before it plays.
    assert segment_lengths(30) == [90]
    assert segment_lengths(40) == [70, 70]
    assert segment_lengths(45) == [86, 86]
    assert segment_lengths(70) == [98] * 5
    assert segment_lengths(95) == [120] * 15  # half an hour between songs at most
    assert segment_lengths(100) == [120]
    assert segment_count(60, 40) == 21  # 24 minutes of talk, 70 seconds at a time
    assert segment_count(60, 100) == 30
    assert segment_count(15, 20) == 3


def test_a_links_move_is_dealt_fairly() -> None:
    rng = random.Random(1)
    last: list[str] = []
    for _ in range(300):
        move = deal_move(rng, PLAIN, guests=False, last=last)
        assert not BY_NAME[move].running
        assert move not in last[-2:]
        # No hooks, so nothing that needs them, and nobody to drop in.
        assert move not in ("the wind-up", "the confession", "the guest")
        last.append(move)
    # Only four moves need no hooks and no guest; with two of them always resting, the
    # order still varies.
    assert len(set(last)) == 4
    assert len({tuple(last[i : i + 4]) for i in range(0, 296, 4)}) > 1

    dealt = {deal_move(rng, [GUILDBERT, DEBBIE], guests=True, last=[]) for _ in range(300)}
    assert {"the wind-up", "the confession", "the guest", "the verdict"} <= dealt
    # With no song just played, as when a show opens, there's no song to give a verdict on.
    hosts = [GUILDBERT, DEBBIE]
    opening = {deal_move(rng, hosts, guests=True, last=[], song=False) for _ in range(300)}
    assert "the verdict" not in opening


def test_a_show_gets_one_or_two_running_bits_unlike_the_last() -> None:
    rng = random.Random(2)
    counts = set()
    for _ in range(100):
        bits = deal_bits(rng, [show("2026-11-13", bits=[("the bet", "Biscuits.")])])
        assert "the bet" not in bits
        assert all(BY_NAME[bit].running for bit in bits)
        counts.add(len(bits))
    assert counts == {1, 2}


def test_four_shows_in_ten_have_a_happening() -> None:
    rng = random.Random(3)
    rolls = [roll_happening(rng, guests=False) for _ in range(2000)]
    happened = [roll for roll in rolls if roll]
    assert 0.36 < len(happened) / len(rolls) < 0.44
    assert "a surprise guest" not in happened
    assert set(happened) == {"an argument", "a prank", "a bet"}


async def _plan(openai: FakeOpenAI, **changes):
    ai = AIClient("test", "gpt-6-astra", "low", http=fake(openai))
    fields = {
        "station": "The Lunch Break",
        "hosts": [GUILDBERT, DEBBIE],
        "dynamic": "Debbie can't let Guildbert finish a story.",
        "prompt": "Light chat. Draw on the [news].",
        "material": {"news": "- 15 Nov: A goat was elected mayor."},
        "starts": LUNCHTIME,
        "minutes": 60,
        "ratio": 30,
        "bits": ["the bet", "the score"],
        "happening": None,
        "log": [
            show("2026-11-13", ["the goat mayor", "Debbie's bees"], [("the challenge", "No rain.")])
        ],
        "until": "13:00",
    }
    try:
        return await plan_show(ai, **(fields | changes))
    finally:
        await ai.close()


@pytest.mark.asyncio
async def test_a_show_is_planned_from_what_it_was_dealt() -> None:
    openai = FakeOpenAI()
    plan = await _plan(openai)
    assert plan["segments"] == [f"Topic {n}" for n in range(1, 13)]
    assert plan["topics"] == [f"topic {n}" for n in range(1, 13)]  # named, for the log
    assert plan["bits"] == [
        {"move": "the bet", "idea": "A biscuit says nobody asks for ABBA.",
         "ending": "Priya asks for ABBA.", "setup": 1, "payoff": 9},
        {"move": "the score", "idea": "Guess the year.", "ending": "A draw.", "setup": 2,
         "payoff": 10},
    ]  # fmt: skip
    assert plan["happening"] is None

    (asked,) = openai.asked_for("show_plan")
    told = asked["instructions"]
    assert "Guildbert: Cheeky. Pet peeves: Songs that fade out." in told
    assert "Debbie: Bubbly. Soft spots: ABBA." in told
    assert "Debbie can't let Guildbert finish a story." in told
    assert "Draw on the [news]." in told
    assert "That's a guide, not a checklist." in told  # strayed from, for variety
    prompt = asked["input"]
    assert "The show runs until 13:00: 12 segments of talk." in prompt
    assert "[news]\n- 15 Nov: A goat was elected mayor." in prompt
    assert "- the bet: Stakes are set early" in prompt
    assert "- 2026-11-13: the challenge, No rain." in prompt
    # What the last shows talked about, so it isn't planned again.
    assert "Listeners have heard these, so don't plan them again" in prompt
    assert "don't retell a story from the news they've had" in prompt
    assert "- 2026-11-13: the goat mayor; Debbie's bees" in prompt
    assert "Name each segment's topic in a few words" in prompt
    assert "leave the happening's idea empty" in prompt
    # Easy to follow: a topic or two a segment, hooks explained, and no segment numbers on air.
    assert "Give each segment one topic, two at most" in prompt
    assert "the first segment to bring up one of a DJ's hooks" in prompt
    assert "never refer to one by its number" in prompt
    assert "never from facts about songs" in prompt


@pytest.mark.asyncio
async def test_a_plan_that_doesnt_fit_the_show_is_made_to() -> None:
    openai = FakeOpenAI()
    openai.plan = {
        "segments": [{"about": "Just the one."}],
        "bits": [
            {"move": "the score", "idea": "Too late.", "ending": "", "setup": 11, "payoff": 40},
            {"move": "the bet", "idea": "Backwards.", "ending": "", "setup": 0, "payoff": 0},
            {"move": "the challenge", "idea": "Not dealt.", "ending": "", "setup": 2, "payoff": 4},
        ],
        "happening": {
            "idea": "Debbie hides Guildbert's headphones.",
            "ending": "He finds them on his head.",
            "starts": 99,
            "ends": 3,
        },
    }
    plan = await _plan(openai, bits=["the bet", "the score"], happening="a prank")
    assert plan["segments"] == ["Just the one."] + ["Whatever comes up."] * 11
    # Matched by name, set up with room to pay off before the last segment, and the bit
    # nobody dealt dropped.
    assert [(b["move"], b["idea"], b["setup"], b["payoff"]) for b in plan["bits"]] == [
        ("the bet", "Backwards.", 1, 3),
        ("the score", "Too late.", 9, 11),
    ]
    assert plan["happening"] == {
        "kind": "a prank",
        "idea": "Debbie hides Guildbert's headphones.",
        "ending": "He finds them on his head.",
        "starts": 12,
        "ends": 12,  # never before it starts
    }

    # A happening the dice didn't roll isn't one.
    plan = await _plan(openai, happening=None)
    assert plan["happening"] is None


def test_the_log_keeps_the_last_few_shows() -> None:
    bit = {"move": "the bet", "idea": "Biscuits.", "ending": "Debbie won.", "setup": 1, "payoff": 4}
    plan = {"bits": [bit], "topics": ["the goat mayor"], "hooks": {"Debbie": ["obsession"]}}
    log: list[dict] = []
    for day in range(SHOWS_KEPT + 5):
        log = logged(log, plan, (date(2026, 9, 1) + timedelta(days=day)).isoformat())
    assert len(log) == SHOWS_KEPT
    # Its bits with how they ended, for calling back to, its topics and the hooks it had.
    assert log[-1] == show(
        "2026-11-04",
        ["the goat mayor"],
        [("the bet", "Biscuits. Debbie won.")],
        {"Debbie": ["obsession"]},
        told=[],
    )


@pytest.mark.asyncio
async def test_a_weeks_topics_are_shown_so_the_weeks_news_isnt_told_twice() -> None:
    openai = FakeOpenAI()
    # Shows from the 1st to the 15th, and the show being planned is on the 16th.
    log = [
        show(f"2026-11-{day:02d}", [f"topic from the {day}th"], [("the bet", f"Bet {day}.")])
        for day in range(1, 16)
    ]
    await _plan(openai, log=log)
    prompt = openai.asked_for("show_plan")[0]["input"]
    shown = [day for day in range(1, 16) if f"topic from the {day}th" in prompt]
    assert shown == list(range(9, 16))  # the week before the 16th
    bets = [day for day in range(1, 16) if f"Bet {day}." in prompt]
    assert bets == list(range(16 - BITS_SHOWN, 16))  # bits from the last few shows only
    assert "newest first" in prompt  # the news goes back a week


def test_each_show_has_a_hook_or_two_of_each_djs_resting_the_last() -> None:
    rng = random.Random(5)
    debbie = Host(
        "Debbie",
        "Bubbly.",
        pet_peeves="Fish in the office microwave.",
        soft_spots="ABBA.",
        obsession="Finding out who nicks her yoghurts.",
    )
    hosts = [debbie, Host("Guildbert", "Cheeky.")]  # he has no hooks
    log: list[dict] = []
    counts, obsessed = set(), 0
    for day in range(200):
        hooks = deal_hooks(rng, hosts, log)
        assert "Guildbert" not in hooks
        had = hooks["Debbie"]
        counts.add(len(had))
        if log:  # none she had last time, while she has others
            assert not set(had) & set(log[-1]["hooks"]["Debbie"])
        obsessed += "obsession" in had
        log = logged(
            log, {"bits": [], "hooks": hooks}, (date(2026, 1, 1) + timedelta(days=day)).isoformat()
        )
    assert counts == {1, 2}
    assert 0.25 < obsessed / 200 < 0.6  # the yoghurts come up in some shows, not every one

    # The show's DJs have only the hooks dealt to it.
    (dealt,) = with_hooks([debbie], {"Debbie": ["soft_spots"]})
    assert (dealt.pet_peeves, dealt.soft_spots, dealt.obsession) == ("", "ABBA.", "")
    assert "yoghurts" not in dealt.described()
    assert with_hooks([debbie], None) == [debbie]  # a plan from before hooks were dealt


def test_a_log_kept_by_bit_is_kept_by_show() -> None:
    path = MIGRATIONS / "versions" / "0026_talk_log_by_show.py"
    spec = importlib.util.spec_from_file_location("log_by_show", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    by_bit = [
        {"on": "2026-11-19", "move": "the bet", "idea": "Biscuits."},
        {"on": "2026-11-20", "move": "the score", "idea": "Odd news numbers."},
        {"on": "2026-11-20", "move": "the challenge", "idea": "No saying cold."},
    ]
    by_show = [
        show("2026-11-19", bits=[("the bet", "Biscuits.")]),
        show(
            "2026-11-20",
            bits=[("the score", "Odd news numbers."), ("the challenge", "No saying cold.")],
        ),
    ]
    assert migration._by_show(by_bit) == by_show
    assert migration._by_bit(by_show) == by_bit


FEATURES = [
    {"name": "Real or Fake?", "does": "One reads an odd headline; the other guesses if it's real."},
    {"name": "Joke of the Day", "does": "One tells a joke; the other rates it out of ten."},
]


def test_a_show_with_features_deals_them_in_place_of_banter() -> None:
    rng = random.Random(1)
    dealt: list[str] = []
    for _ in range(300):
        dealt.append(deal_move(rng, [GUILDBERT, DEBBIE], True, dealt, features=FEATURES))
    # A guest drops in as often as any one feature, and none comes twice running.
    assert set(dealt) == {"Real or Fake?", "Joke of the Day", "the guest"}
    assert all(a != b for a, b in zip(dealt, dealt[1:], strict=False))
    assert 70 < dealt.count("the guest") < 130
    # With no other DJ to drop in, just the features, in no fixed order.
    alone = [deal_move(rng, PLAIN, False, [], features=FEATURES) for _ in range(50)]
    assert set(alone) == {"Real or Fake?", "Joke of the Day"}


def test_a_show_with_features_only_has_guests_drop_in() -> None:
    rng = random.Random(3)
    rolls = [roll_happening(rng, guests=True, banter=False) for _ in range(500)]
    assert set(rolls) == {None, "a surprise guest"}
    assert not any(roll_happening(rng, guests=False, banter=False) for _ in range(100))


@pytest.mark.asyncio
async def test_the_planner_hears_of_the_features_and_whats_been_told() -> None:
    openai = FakeOpenAI()
    log = [
        show("2026-11-02", told=["joke: far too old"]),
        show("2026-11-13", ["the goat mayor"], told=["joke: the goat at the polls"]),
    ]
    await _plan(openai, log=log, features=FEATURES)
    prompt = openai.asked_for("show_plan")[0]["input"]
    assert "- Real or Fake?: One reads an odd headline" in prompt
    assert "Keep each segment to one topic, so there's room for a feature in it." in prompt
    assert "- 2026-11-13: joke: the goat at the polls" in prompt
    assert "far too old" not in prompt  # more than a week before the 16th


def test_what_was_told_is_kept_with_todays_show_for_a_week() -> None:
    log = logged([], {"bits": [], "topics": []}, "2026-11-10")
    log = with_told(log, "2026-11-10", ["joke: the peahen", " "])
    assert with_told(log, "2026-11-11", ["story: another day's"]) == log  # not today's show
    assert log[-1]["told"] == ["joke: the peahen"]
    log = logged(log, {"bits": [], "topics": []}, "2026-11-17")
    assert log[0]["told"] == ["joke: the peahen"]  # a week on, still kept
    assert told_lately(log, date(2026, 11, 17)) == "- 2026-11-10: joke: the peahen"
    log = logged(log, {"bits": [], "topics": []}, "2026-11-18")
    assert "told" not in log[0]  # over a week old
    assert told_lately(log, date(2026, 11, 18)) == ""


def test_only_the_newest_of_whats_been_told_is_shown() -> None:
    log = [
        show(f"2026-11-{day}", told=[f"joke {day}-{n}" for n in range(100)]) for day in (14, 15, 16)
    ]
    shown = told_lately(log, date(2026, 11, 16))
    assert shown.count("joke") == TOLD_SHOWN
    assert "joke 16-99" in shown and "joke 15-0;" in shown and "joke 14-" not in shown
    assert shown.index("2026-11-15") < shown.index("2026-11-16")  # oldest first
