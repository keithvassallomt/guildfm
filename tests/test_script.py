"""Talk stations: writing a segment, and voicing it so the DJs talk over each other."""

import json
import random
from pathlib import Path

import pytest

from guildfm.ai import AIClient
from guildfm.audio import FFMPEG
from guildfm.mixing import OVERLAP, TOGETHER, placed, voice_segment
from guildfm.script import Moment, Turn, brief, checked, write_segment
from guildfm.speech import Clip, SpeechClient, Timed, mp3_seconds
from guildfm.talk import Host
from tests.conftest import fake
from tests.fakes import FakeElevenLabs, FakeOpenAI, mp3

PLAN = {
    "segments": ["Hello", "Biscuits", "Football", "Goodbye"],
    "bits": [{"move": "the bet", "idea": "A biscuit says nobody asks for ABBA.", "setup": 1,
              "payoff": 3}],
    "happening": {"kind": "a prank", "idea": "Debbie hides his headphones.", "starts": 2},
}  # fmt: skip
CLOCK = "It's Monday 16 November, 12:40, lunchtime."


def test_marks_that_cant_work_come_off() -> None:
    turns, notes = checked(
        [
            Turn("Guildbert", "I was going to say something about biscuits.", "not in it"),
            Turn("Debbie", "Go on then, tell us about the biscuits.", "the biscuits."),
            Turn("Guildbert", "Well, the thing about biscuits is the crumbs.", "the thing"),
            Turn("Debbie", "Crumbs!", together=True),  # comes in after a cut, not with it
            Turn("Debbie", "Honestly, the crumbs get everywhere.", "Honestly, the"),
            Turn("Debbie", "Everywhere, Guildbert.", together=True),  # the same DJ
            Turn("Guildbert", "One, two, three, four, five, six.", "One, two"),
            Turn("Debbie", "Seven, eight, nine, ten, eleven.", "Seven, eight"),
            Turn("Guildbert", "Twelve, thirteen, fourteen.", "Twelve,"),
        ]
    )
    assert [t.cut_after for t in turns] == ["", "", "the thing", "", "", "", "One, two", "", ""]
    assert not any(t.together for t in turns)
    assert turns[3].text == "[interrupting] Crumbs!"
    assert turns[7].text == "[interrupting] Seven, eight, nine, ten, eleven."
    assert turns[8].text == "Twelve, thirteen, fourteen."
    assert notes == [
        "Turn 1 isn't cut: its words aren't in it.",
        "Turn 2 isn't cut: the words are at its very end.",
        "Turn 4 isn't said together with the one before.",
        "Turn 5 isn't cut: the same DJ speaks next.",
        "Turn 6 isn't said together with the one before.",
        "Turn 8 isn't cut: there are already 2 cuts.",
        "Turn 9 isn't cut: it's the last turn.",
    ]


def test_turns_that_are_fine_keep_their_marks() -> None:
    turns, notes = checked(
        [
            Turn("Guildbert", "Right, before you start, I have a theory.", "before you start"),
            Turn("Debbie", "[laughs] No theories."),
            Turn("Guildbert", "No!"),
            Turn("Debbie", "No!", together=True),
        ]
    )
    assert notes == []
    assert turns[1].text == "[laughs] No theories."  # already tagged
    assert (turns[0].cut_after, turns[3].together) == ("before you start", True)


def test_the_writer_is_told_what_this_segment_is_for() -> None:
    said = [[Turn("Guildbert", "Afternoon, all."), Turn("Debbie", "Hiya!")]]
    middle = Moment(
        number=2,
        count=4,
        clock=CLOCK,
        until="13:00",
        before='"Dreams" by Fleetwood Mac',
        move="the verdict",
        skipped=1,
    )
    told = brief(PLAN, middle, {"news": "- A goat was elected mayor."}, "Debbie leads.", said, 120)
    for expected in (
        CLOCK,
        "The show runs until 13:00.",
        "This is segment 2 of 4.",
        'Just played: "Dreams" by Fleetwood Mac.',
        "This segment is about: Biscuits",
        "the bet is running (A biscuit says nobody asks for ABBA.)",
        "The happening, a prank, starts now: Debbie hides his headphones.",
        "Somewhere in this link, the verdict: Both rate the last song, and disagree.",
        "Listeners didn't hear segment 1",
        "The show's notes so far: Debbie leads.",
        "[news]\n- A goat was elected mayor.",
        "Guildbert: Afternoon, all.\nDebbie: Hiya!",
        "Write about 2040 characters of speech, about 120 seconds.",
    ):
        assert expected in told

    first = brief(PLAN, Moment(number=1, count=4, clock=CLOCK, first=True), {}, "", [], 60)
    assert "It opens the show: welcome everyone" in first
    assert "Set up the bet now: A biscuit says nobody asks for ABBA." in first
    paying = brief(PLAN, Moment(number=3, count=4, clock=CLOCK), {}, "", [], 60)
    assert "Pay off the bet now" in paying
    assert "The happening, a prank, is under way" in paying
    ending = Moment(number=4, count=4, clock=CLOCK, last=True, ends_link=True, up_next="ABBA")
    told = brief(PLAN, ending, {}, "", [], 60)
    assert "pay off anything still running, and sign off" in told
    assert "End by bringing in the next one: ABBA" in told


@pytest.mark.asyncio
async def test_a_segment_is_written_and_checked() -> None:
    openai = FakeOpenAI()
    openai.segment["turns"].append(
        {"speaker": "Somebody", "text": "Hello?", "cut_after": "", "together": False}
    )
    ai = AIClient("test", "gpt-6-astra", "low", http=fake(openai))
    try:
        turns, notes, problems = await write_segment(
            ai,
            station="The Lunch Break",
            hosts=[Host("Guildbert", "Cheeky."), Host("Debbie", "Bubbly.")],
            dynamic="Debbie can't let Guildbert finish a story.",
            prompt="Light chat.",
            plan=PLAN,
            moment=Moment(number=3, count=4, clock=CLOCK),
            material={},
            notes="Debbie leads.",
            said=[],
            seconds=120,
        )
    finally:
        await ai.close()
    assert [t.speaker for t in turns] == ["Guildbert", "Debbie"]  # nobody else
    assert turns[0].cut_after == "before you start"
    assert turns[1].text.startswith("[interrupting]")
    assert notes == "Debbie has won the biscuit."
    assert problems == []
    (asked,) = openai.asked_for("talk_segment")
    speaker = asked["text"]["format"]["schema"]["properties"]["turns"]["items"]["properties"]
    assert speaker["speaker"]["enum"] == ["Guildbert", "Debbie"]
    assert "Debbie can't let Guildbert finish a story." in asked["instructions"]


def timed(path: Path, text: str, seconds: float = 2.0) -> Timed:
    """`text` said evenly through a clip, after a tenth of a second."""
    step = (seconds - 0.2) / len(text)
    starts = [0.1 + i * step for i in range(len(text))]
    return Timed(Clip(path, seconds), list(text), starts, [s + step for s in starts])


def test_turns_are_placed_to_talk_over_each_other(tmp_path: Path) -> None:
    turns = [
        Turn("Guildbert", "one two three four five six seven", cut_after="three four"),
        Turn("Debbie", "[interrupting] eight nine ten"),
        Turn("Guildbert", "No!", together=True),
        Turn("Debbie", "Right."),
    ]
    clips = [timed(tmp_path / f"{n}.mp3", turn.text) for n, turn in enumerate(turns)]
    parts = placed(turns, clips, random.Random(1))

    cut = parts[0]
    assert cut.fade and cut.at == 0.0
    cut_at = cut.at + cut.end - cut.start
    # "three four" ends just over halfway through the first clip.
    assert 1.05 < cut.end < 1.15
    # Debbie's first word comes in a fifth of a second before the cut.
    debbie_speaks = parts[1].at + (clips[1].starts[15] - parts[1].start)
    assert debbie_speaks == pytest.approx(cut_at - OVERLAP, abs=0.002)
    # Guildbert's "No!" starts with Debbie's turn, give or take a moment.
    no_speaks = parts[2].at + (clips[2].starts[0] - parts[2].start)
    assert debbie_speaks <= no_speaks <= debbie_speaks + TOGETHER
    # Debbie's last turn waits for both to finish.
    ends = [p.at + p.end - p.start for p in parts[1:3]]
    assert parts[3].at > max(ends) - 0.2


@pytest.mark.asyncio
async def test_a_segment_is_voiced_turn_by_turn_and_mixed(tmp_path: Path) -> None:
    elevenlabs = FakeElevenLabs()
    speech = SpeechClient("test", "gpt-4o-mini-tts", tmp_path, http=fake(elevenlabs),
                          eleven_key="eleven-test")  # fmt: skip
    turns, _ = checked(
        [
            Turn("Guildbert", "Right, before you start, I have a theory.", "before you start"),
            Turn("Debbie", "No theories."),
        ]
    )
    voices = {"Guildbert": "elevenlabs:guildbert01", "Debbie": "elevenlabs:aurora02"}
    try:
        clip = await voice_segment(speech, turns, voices, random.Random(1))
        assert clip.path.exists()
        if FFMPEG:  # cut and overlapping: shorter than the two clips end to end
            assert 0 < clip.seconds < 2 * elevenlabs.seconds
        else:
            assert clip.path.read_bytes() == mp3(elevenlabs.seconds) * 2
        assert [r["voice"] for r in elevenlabs.requests] == ["guildbert01", "aurora02"]
        # Each turn is told the one before, without its tags, so it sounds like a reply.
        assert "previous_text" not in elevenlabs.requests[0]
        assert (
            elevenlabs.requests[1]["previous_text"] == "Right, before you start, I have a theory."
        )
        # Each turn's timings are kept beside it, so voicing it again asks for nothing.
        timings = sorted((tmp_path / "speech").glob("*.json"))
        assert len(timings) == 2
        assert json.loads(timings[0].read_text())["characters"]
        again = await voice_segment(speech, turns, voices, random.Random(1))
        assert len(elevenlabs.requests) == 2
        assert mp3_seconds(again.path.read_bytes()) == pytest.approx(clip.seconds)
    finally:
        await speech.close()
