"""Talk stations: the banter moves, the dice and the show plan."""

import importlib.util
import random
from datetime import datetime

import pytest

from guildfm.ai import AIClient
from guildfm.db import MIGRATIONS
from guildfm.talk import (
    BY_NAME,
    SHOWS_KEPT,
    TOPICS_SHOWN,
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
    with_hooks,
)
from tests.conftest import fake
from tests.fakes import FakeOpenAI


def show(
    on: str,
    topics: list[str] | None = None,
    bits: list[tuple[str, str]] = (),
    hooks: dict[str, list[str]] | None = None,
) -> dict:
    """A show in a station's log."""
    return {
        "on": on,
        "bits": [{"move": move, "idea": idea} for move, idea in bits],
        "topics": topics or [],
        "hooks": hooks or {},
    }


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
    assert "Listeners have heard these, so don't plan them again." in prompt
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
    for day in range(1, 20):
        log = logged(log, plan, f"2026-11-{day:02d}")
    assert len(log) == SHOWS_KEPT
    # Its bits with how they ended, for calling back to, its topics and the hooks it had.
    assert log[-1] == show(
        "2026-11-19",
        ["the goat mayor"],
        [("the bet", "Biscuits. Debbie won.")],
        {"Debbie": ["obsession"]},
    )


@pytest.mark.asyncio
async def test_only_the_last_few_shows_topics_are_shown() -> None:
    openai = FakeOpenAI()
    log = [show(f"2026-11-{day:02d}", [f"topic from the {day}th"]) for day in range(10, 15)]
    await _plan(openai, log=log)
    prompt = openai.asked_for("show_plan")[0]["input"]
    shown = [day for day in range(10, 15) if f"topic from the {day}th" in prompt]
    assert shown == list(range(15 - TOPICS_SHOWN, 15))


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
        log = logged(log, {"bits": [], "hooks": hooks}, str(day))
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
