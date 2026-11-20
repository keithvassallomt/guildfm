"""Talk stations: writing a segment, and voicing it so the DJs talk over each other."""

import json
import random
import re
from pathlib import Path

import pytest

from guildfm.ai import AIClient
from guildfm.audio import FFMPEG
from guildfm.mixing import OVERLAP, TOGETHER, placed, voice_segment
from guildfm.script import (
    INSTRUCTIONS,
    MENTIONS,
    SONG,
    Moment,
    Segment,
    Turn,
    brief,
    checked,
    deal_mention,
    remembered,
    write_segment,
)
from guildfm.speech import Clip, SpeechClient, Timed, mp3_seconds
from guildfm.talk import Host
from tests.conftest import fake
from tests.fakes import FakeElevenLabs, FakeOpenAI, mp3

PLAN = {
    "segments": ["Hello", "Biscuits", "Football", "Goodbye"],
    "bits": [{"move": "the bet", "idea": "A biscuit says nobody asks for ABBA.",
              "ending": "Priya asks for ABBA.", "setup": 1, "payoff": 3}],
    "happening": {"kind": "a prank", "idea": "Debbie hides his headphones.",
                  "ending": "They're on his head.", "starts": 2, "ends": 3},
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
        "It's early in the show.",
        'A song has just finished: "Dreams" by Fleetwood Mac. The conversation stopped for it, '
        "so don't pick up mid-exchange as if it hadn't.",
        "Then they go back to where they left off, saying in a line what it was, or move on",
        "This segment is about: Biscuits",
        "the bet is under way, and pays off later: don't settle it or bring it to a head now. A "
        "biscuit says nobody asks for ABBA.",
        "The happening, a prank, starts now: Debbie hides his headphones. It comes to a head "
        "later: don't settle it now.",
        "Somewhere in this link, within what it's about, the verdict: Both rate the last song",
        "Listeners didn't hear the last segment",
        "The show's notes so far: Debbie leads.",
        "[news]\n- A goat was elected mayor.",
        "Guildbert: Afternoon, all.\nDebbie: Hiya!",
        # Where the music came, up to the song that has just finished.
        'Hiya!\n\n[A song played: "Dreams" by Fleetwood Mac. It has just finished.]',
        "Write about 2040 characters of speech, about 120 seconds.",
    ):
        assert expected in told
    # Segments have no numbers here, so none can be copied onto the air.
    assert not re.search(r"segment \d", told, re.IGNORECASE)

    # The opening welcomes everyone, rather than talking about whatever played before the show.
    opening = Moment(number=1, count=4, clock=CLOCK, first=True, before='"Dreams"')
    first = brief(PLAN, opening, {}, "", [], 60)
    assert "It opens the show: welcome everyone" in first
    assert "Dreams" not in first
    assert "Set up the bet now, so listeners get what it is and what's at stake" in first
    # Endings are told only when they're due, so they aren't played out early.
    assert "Priya asks for ABBA" not in first and "Priya asks for ABBA" not in told
    assert "on his head" not in told
    paying = brief(PLAN, Moment(number=3, count=4, clock=CLOCK), {}, "", [], 60)
    assert "Pay off the bet now, reminding listeners in a line what it was" in paying
    assert "How it ends: Priya asks for ABBA." in paying
    assert "The happening, a prank, comes to a head now" in paying
    assert "How it ends: They're on his head." in paying
    ending = Moment(number=4, count=4, clock=CLOCK, last=True, ends_link=True, up_next="ABBA")
    told = brief(PLAN, ending, {}, "", [], 60)
    assert "the bet is settled: Priya asks for ABBA. Don't start it again." in told
    assert "The happening, a prank, is over: They're on his head." in told
    assert "pay off anything still running, and sign off" in told
    # Before a song, the conversation is wrapped up, not left hanging over it.
    assert "wrap up first: land what they're on, or park it openly" in told
    assert "End by bringing in the next one: ABBA" in told


def test_a_segment_with_no_song_before_it_carries_straight_on() -> None:
    said = [[Turn("Guildbert", "So the thing about marrows is"), Turn("Debbie", "Go on.")]]
    moment = Moment(number=3, count=4, clock=CLOCK, straight_on=True)
    told = brief(PLAN, moment, {}, "", said, 120)
    assert "It carries straight on from the last segment, with no song between" in told
    assert "A song has just finished" not in told
    assert "[A song played" not in told


def test_the_song_before_is_named_reacted_to_or_left_alone_in_turn() -> None:
    rng = random.Random(1)
    last, dealt = None, []
    for _ in range(30):
        mention = deal_mention(rng, last, "the bet")
        assert mention != last  # never the same way twice running
        dealt.append(mention)
        last = mention
    assert set(dealt) == set(MENTIONS)
    # Rating the song is a reaction to it, whatever came last.
    assert deal_mention(rng, "react", "the verdict") == "react"

    for mention, told_to in MENTIONS.items():
        moment = Moment(number=2, count=4, clock=CLOCK, before='"Dreams"', mention=mention)
        told = brief(PLAN, moment, {}, "", [], 120)
        assert told_to in told
        assert all(other not in told for other in MENTIONS.values() if other != told_to)
    assert 'Not "That was ... by ..."' in MENTIONS["react"]


def test_what_was_said_is_kept_with_the_songs_between() -> None:
    turns = [Turn("Debbie", "You've got a problem with always wanting a fresh coat!")]
    after = Moment(number=2, count=4, clock=CLOCK, before='"Dreams" by Fleetwood Mac')
    on = Moment(number=3, count=4, clock=CLOCK, before='"Dreams"', straight_on=True)
    assert remembered(after, turns) == [Turn(SONG, '"Dreams" by Fleetwood Mac'), *turns]
    assert remembered(on, turns) == turns  # no song came before it

    # The next segment, after another song, reads where both songs came.
    said = [remembered(after, turns)]
    next_one = Moment(number=3, count=4, clock=CLOCK, before='"Rumours" by Fleetwood Mac')
    told = brief(PLAN, next_one, {}, "", said, 120)
    assert (
        '[A song played: "Dreams" by Fleetwood Mac]\n'
        "Debbie: You've got a problem with always wanting a fresh coat!\n\n"
        '[A song played: "Rumours" by Fleetwood Mac. It has just finished.]'
    ) in told
    assert "Never carry on mid-exchange as if no song had played." in INSTRUCTIONS


@pytest.mark.asyncio
async def test_a_segment_is_written_and_checked() -> None:
    openai = FakeOpenAI()
    openai.segment["turns"].append(
        {"speaker": "Somebody", "text": "Hello?", "cut_after": "", "together": False}
    )
    ai = AIClient("test", "gpt-6-astra", "low", http=fake(openai))
    try:
        segment = await write_segment(
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
    turns = segment.turns
    assert [t.speaker for t in turns] == ["Guildbert", "Debbie"]  # nobody else
    assert turns[0].cut_after == "before you start"
    assert turns[1].text.startswith("[interrupting]")
    assert segment.notes == "Debbie has won the biscuit."
    assert (segment.marks, segment.fixed, segment.draft) == ([], [], [])  # nothing to fix
    (asked,) = openai.asked_for("talk_segment")
    speaker = asked["text"]["format"]["schema"]["properties"]["turns"]["items"]["properties"]
    assert speaker["speaker"]["enum"] == ["Guildbert", "Debbie"]
    assert "Debbie can't let Guildbert finish a story." in asked["instructions"]
    assert 'never say "segment"' in asked["instructions"]
    assert "Whoever brings up a story tells it first" in asked["instructions"]


@pytest.mark.asyncio
async def test_a_segment_that_says_segment_on_air_is_written_again() -> None:
    openai = FakeOpenAI()
    leaky = json.loads(json.dumps(openai.segment))
    leaky["turns"][1]["text"] = "Save it for segment four, Guildbert."
    openai.segments_in_turn = [leaky]
    ai = AIClient("test", "gpt-6-astra", "low", http=fake(openai))
    try:
        segment = await write_segment(
            ai,
            station="The Lunch Break",
            hosts=[Host("Guildbert", "Cheeky."), Host("Debbie", "Bubbly.")],
            dynamic="",
            prompt="",
            plan=PLAN,
            moment=Moment(number=1, count=4, clock=CLOCK, first=True),
            material={},
            notes="",
            said=[],
            seconds=120,
        )
    finally:
        await ai.close()
    first, again = openai.asked_for("talk_segment")
    assert "Listeners never hear of segments" in again["input"]
    assert "segment" not in segment.turns[1].text
    assert segment.marks == []


DRAFT = [
    {"speaker": "Debbie", "text": "Your marrows again, Guildbert!", "cut_after": "",
     "together": False},
    {"speaker": "Guildbert", "text": "He measured them, Debbie. With a tape, mind.",
     "cut_after": "He measured them", "together": False},
    {"speaker": "Debbie", "text": "[laughs] Who does that?", "cut_after": "", "together": False},
]  # fmt: skip


async def _write(openai: FakeOpenAI, **changes) -> Segment:
    openai.segment = {"turns": DRAFT, "notes": "Marrows explained."}
    ai = AIClient("test", "gpt-6-astra", "low", http=fake(openai))
    fields = {
        "station": "The Lunch Break",
        "hosts": [
            Host("Guildbert", "Dry.", obsession="His allotment's marrows."),
            Host("Debbie", "Bubbly."),
        ],
        "dynamic": "Debbie can't let Guildbert finish a story.",
        "prompt": "Light chat.",
        "plan": PLAN,
        "moment": Moment(number=2, count=4, clock=CLOCK, before='"Dreams" by Fleetwood Mac'),
        "material": {"news": "- A goat was elected mayor."},
        "notes": "The bet is on.",
        "said": [[Turn("Guildbert", "Afternoon, all."), Turn("Debbie", "Hiya!")]],
        "seconds": 120,
    }
    try:
        return await write_segment(ai, **(fields | changes))
    finally:
        await ai.close()


@pytest.mark.asyncio
async def test_a_segment_is_edited_for_listeners_who_werent_told() -> None:
    openai = FakeOpenAI()
    fixed = [
        {"speaker": "Debbie", "text": "Guildbert grows marrows on his allotment, and the man two "
         "plots down measures them. Your marrows again, Guildbert!", "cut_after": "",
         "together": False},
        *DRAFT[1:],
    ]  # fmt: skip
    problem = "Turn 1 mentions his marrows, which listeners haven't heard about."
    openai.edit = {"problems": [problem], "turns": fixed}
    segment = await _write(openai)
    assert segment.turns[0].text.startswith("Guildbert grows marrows on his allotment")
    assert segment.turns[1].cut_after == "He measured them"  # its marks kept, and checked
    assert segment.turns[2].text == "[laughs] Who does that?"
    assert segment.fixed == [problem]
    assert segment.draft[0].text == "Your marrows again, Guildbert!"

    # The editor reads it as a listener, apart from the background it can use to fix it.
    (asked,) = openai.asked_for("talk_edit")
    assert "Is everything explained?" in asked["instructions"]
    assert "Does it follow?" in asked["instructions"]
    assert "carries on mid-exchange after a song as if it hadn't played" in asked["instructions"]
    assert asked["input"].startswith(f"{CLOCK}\n\nWHAT LISTENERS HAVE HEARD")  # not guessed
    heard, background = asked["input"].split("BACKGROUND")
    assert 'A song has just finished: "Dreams" by Fleetwood Mac.' in heard
    assert '[A song played: "Dreams" by Fleetwood Mac. It has just finished.]' in heard
    assert "After the draft, a song plays" not in asked["input"]
    assert "as the show's notes have it: The bet is on." in heard
    assert "Guildbert: Afternoon, all.\nDebbie: Hiya!" in heard
    assert "marrows" not in heard
    assert "Keeps coming back to: His allotment's marrows." in background
    assert "[news]\n- A goat was elected mayor." in background
    assert '"Your marrows again, Guildbert!"' in background  # the draft, last


@pytest.mark.asyncio
async def test_the_editor_knows_when_a_song_follows_the_draft() -> None:
    openai = FakeOpenAI()
    moment = Moment(number=2, count=4, clock=CLOCK, ends_link=True, up_next='"Dreams"')
    await _write(openai, moment=moment)
    (asked,) = openai.asked_for("talk_edit")
    assert 'After the draft, a song plays: "Dreams"\n\nThe draft:\n' in asked["input"]
    assert "ends before a song on a question or a point left hanging" in asked["instructions"]


@pytest.mark.asyncio
async def test_an_edit_that_cant_be_used_leaves_the_draft() -> None:
    openai = FakeOpenAI()
    # It found something, but cut nearly all of it.
    openai.edit = {"problems": ["Turn 2 is odd."], "turns": DRAFT[2:]}
    segment = await _write(openai)
    assert [t.text for t in segment.turns][0] == "Your marrows again, Guildbert!"
    assert (segment.fixed, segment.draft) == ([], [])

    # An edit that can't be had: the draft goes out as written.
    openai = FakeOpenAI()
    openai.edit_down = True
    segment = await _write(openai)
    assert len(segment.turns) == 3 and segment.fixed == []

    # At the opening, listeners haven't heard anything from them yet.
    openai = FakeOpenAI()
    segment = await _write(openai, moment=Moment(number=1, count=4, clock=CLOCK, first=True))
    (asked,) = openai.asked_for("talk_edit")
    assert "listeners haven't heard these DJs yet today" in asked["input"]
    assert "Afternoon, all." not in asked["input"]


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
