"""Talk stations: the banter moves, the dice and the show plan."""

import random
from datetime import datetime

import pytest

from guildfm.ai import AIClient
from guildfm.talk import (
    BY_NAME,
    LOG_KEPT,
    Host,
    deal_bits,
    deal_move,
    link_seconds,
    logged,
    plan_show,
    roll_happening,
    segment_count,
)
from tests.conftest import fake
from tests.fakes import FakeOpenAI

GUILDBERT = Host("Guildbert", "Cheeky.", pet_peeves="Songs that fade out.")
DEBBIE = Host("Debbie", "Bubbly.", soft_spots="ABBA.")
PLAIN = [Host("Guildbert", "Cheeky."), Host("Debbie", "Bubbly.")]  # no hooks at all
LUNCHTIME = datetime(2026, 11, 16, 12, 0)


def test_talk_takes_its_share_of_the_time() -> None:
    assert link_seconds(50) == 210  # as long as a song
    assert link_seconds(40) == 140
    assert link_seconds(80) == 840  # 14 minutes between songs
    assert link_seconds(100) is None  # no songs: it runs on
    assert segment_count(60, 40) == 12
    assert segment_count(60, 100) == 30
    assert segment_count(15, 20) == 2


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
        bits = deal_bits(rng, [{"on": "2026-11-13", "move": "the bet", "idea": "Biscuits."}])
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
        "ratio": 40,
        "bits": ["the bet", "the score"],
        "happening": None,
        "log": [{"on": "2026-11-13", "move": "the challenge", "idea": "No saying rain."}],
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
    prompt = asked["input"]
    assert "The show runs until 13:00: 12 segments of talk." in prompt
    assert "[news]\n- 15 Nov: A goat was elected mayor." in prompt
    assert "- the bet: Stakes are set early" in prompt
    assert "- 2026-11-13: the challenge, No saying rain." in prompt
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


def test_the_log_keeps_the_last_few_bits() -> None:
    bit = {"move": "the bet", "idea": "Biscuits.", "ending": "Debbie won.", "setup": 1, "payoff": 4}
    plan = {"bits": [bit]}
    log: list[dict[str, str]] = []
    for day in range(1, 20):
        log = logged(log, plan, f"2026-11-{day:02d}")
    assert len(log) == LOG_KEPT
    # How it ended too, for calling back to.
    assert log[-1] == {"on": "2026-11-19", "move": "the bet", "idea": "Biscuits. Debbie won."}
