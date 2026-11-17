"""Writing a talk station's segments: about two minutes of its DJs talking, as turns, for a
segment of a show planned in talk.py.

The AI marks where one DJ cuts another off (`cut_after`, the words heard before the next DJ cuts
in) and where two say something at the same moment (`together`). The code checks the marks
rather than trusting them, so a mark that can't work comes off. The turns are voiced one at a
time and mixed so the DJs really talk over each other (mixing.py)."""

import re
from dataclasses import dataclass
from typing import Any

from guildfm.ai import AIClient, object_schema
from guildfm.talk import BY_NAME, Host

PER_SECOND = 17  # characters of speech a second, as ElevenLabs' eleven_v4 speaks
MAX_CUTS = 2  # interruptions in a segment, so they stay a character trait
SAID_KEPT = 2  # segments before this one the writer reads in full
_SEGMENT = re.compile(r"\bsegments?\b", re.IGNORECASE)
AGAIN = (
    'An earlier draft of this had a DJ say "segment" on air. Listeners never hear of '
    "segments: write it without the word."
)

INSTRUCTIONS = """You write the talk on {station}, a radio station playing over the speakers in \
an office in the UK. This show is mostly talk, and it has these DJs:

{hosts}

How they get on: {dynamic}

What the show is about, in its producer's words:
{prompt}

Write what they say next as a list of turns. Make it sound like people talking, not one \
person split in two:
- They have different opinions, and say so. They don't praise each other's points or finish \
each other's sentences.
- Each keeps to their own way of talking.
- Turns vary in length: a story, a two-word reply, a line that gets cut off.
- They use each other's names now and then, so listeners learn who's who.
- They tease each other freely, and go gently on the people who request songs.
- Never make up facts about a real person, a song, an artist or a listener. Trivia, news and \
corrections come only from what you're given; leave out anything you aren't sure of.
- No politics, religion or tragedy.

Listeners know only what they hear, so make it easy to follow, as if someone has just walked \
into the room:
- Each turn follows from the one before it: it answers it, reacts to it, argues with it or \
builds on it. Nobody carries on with a thought of their own as if the other hadn't spoken.
- Whoever brings up a story tells it first, plainly, in a sentence or two: what happened, \
where, and to whom. Only then do they react to it and argue about it.
- Everything else you're told (the DJs' hooks, the plan, the show's notes) is news to \
listeners the first time it comes up on air, so explain it then. If a DJ keeps bees, say so \
before joking about the bees.
- The DJs' hooks are seasoning: one comes up now and then, not in every segment. The last \
segments show what's had an airing lately.
- Stay on a topic long enough for it to land, then move on the way people do: from \
something just said, or openly, such as "Right, the weather." Never jump to a new topic in \
the middle of a turn.
- Keep to what this segment is about. Leave the rest of what's going on for other segments.
- A running bit that isn't due now comes up in a line at most, and only if it fits. Don't \
restate its stakes.
- Segments are how the show is planned, and listeners never hear of them: on air, never \
say "segment" or a number for one. Say "after this song", "later" or "before the end of \
the show" instead.

They cut each other off, once or twice in a segment at most, when it suits who they are. For a \
turn that gets cut off, write the whole sentence as the speaker meant to say it, and set \
cut_after to the last two or three words heard before the other DJ cuts in, copied exactly \
from that turn and well before its end. Start the next turn with [interrupting]. For every \
other turn, cut_after is empty.

Now and then two of them say something short at the same moment, such as both saying "No!": \
mark the second of the two turns together. For every other turn, together is false.

It's read out by an expressive text to speech model. An audio tag in square brackets before \
the words it's for steers the delivery, such as [laughs], [sighs], [sarcastic], [excited], \
[whispers] or [interrupting]. Use four at most in a segment, besides [interrupting]. No other \
stage directions, sound effects or emoji.

Also keep the show's notes: in a line or two, the state of its running bits after this \
segment, such as the score, the stakes, who owes whom, and what listeners have been told. \
No segment numbers."""


@dataclass(frozen=True)
class Turn:
    speaker: str  # a DJ's name
    text: str
    cut_after: str = ""  # cut off just after these words, which are in the text
    together: bool = False  # said at the same moment as the turn before


@dataclass(frozen=True)
class Moment:
    """Where a segment falls in the show, and what's going on around it."""

    number: int  # of the show's segments, from 1
    count: int  # the show's segments; more may follow an hour's plan outside a line-up
    clock: str  # such as "It's Monday 16 November, 12:40, lunchtime."
    first: bool = False  # opens the show: welcome everyone
    last: bool = False  # the show's last segment: pay everything off and sign off
    ends_link: bool = False  # songs resume after it
    straight_on: bool = False  # follows the segment before it with no song between
    before: str | None = None  # the song that just played, such as '"Dreams" by Fleetwood Mac'
    up_next: str | None = None  # the song it brings in, with any shout-out, at the link's end
    move: str | None = None  # the move dealt for this link, on its first segment
    skipped: int | None = None  # a segment listeners didn't hear, skipped by a curator
    until: str | None = None  # when the show ends, in a line-up
    guest: str | None = None  # another DJ dropping in for this segment, as Host.described has them
    # About the song it brings in: its play history, repeat requests and the votes (dj.py).
    remarks: tuple[str, ...] = ()


def _schema(names: list[str]) -> dict[str, Any]:
    """A segment, as the writer answers: its turns, by DJs named in `names`, and the notes."""
    turn = object_schema(
        speaker={"type": "string", "enum": names},
        text={"type": "string"},
        cut_after={"type": "string"},
        together={"type": "boolean"},
    )
    return object_schema(turns={"type": "array", "items": turn}, notes={"type": "string"})


def _due(plan: dict[str, Any], number: int) -> list[str]:
    """What the plan has for segment `number`: its subject, and the bits and happening due. A
    bit's ending is told only when it's due, so it isn't played out early."""
    lines = []
    if 0 < number <= len(plan["segments"]):
        lines.append(f"This segment is about: {plan['segments'][number - 1]}")
    for bit in plan["bits"]:
        move, idea, ending = bit["move"], bit["idea"], bit.get("ending", "")
        if bit["setup"] == number:
            lines.append(
                f"Set up {move} now, so listeners get what it is and what's at stake: {idea} It "
                "pays off later in the show: don't settle it now."
            )
        elif bit["payoff"] == number:
            lines.append(
                f"Pay off {move} now, reminding listeners in a line what it was: {idea} How it "
                f"ends: {ending}"
            )
        elif bit["setup"] < number < bit["payoff"]:
            lines.append(
                f"{move} is under way, and pays off later: don't settle it or bring it to a head "
                f"now. {idea}"
            )
        elif number > bit["payoff"]:
            lines.append(f"{move} is settled: {ending} Don't start it again.")
    happening = plan.get("happening")
    if happening:
        kind, idea, ending = happening["kind"], happening["idea"], happening.get("ending", "")
        starts = happening["starts"]
        ends = happening.get("ends", starts)
        if starts == number == ends:
            lines.append(f"The happening, {kind}, starts now: {idea} How it ends: {ending}")
        elif starts == number:
            lines.append(
                f"The happening, {kind}, starts now: {idea} It comes to a head later: don't "
                "settle it now."
            )
        elif starts < number < ends:
            lines.append(
                f"The happening, {kind}, is under way, and comes to a head later: don't settle it "
                f"now. {idea}"
            )
        elif number == ends:
            lines.append(
                f"The happening, {kind}, comes to a head now: {idea} How it ends: {ending}"
            )
        elif number > ends:
            lines.append(f"The happening, {kind}, is over: {ending} Don't start it again.")
    return lines


def _where(moment: Moment) -> str | None:
    """Roughly how far through the show a segment falls, when the show's end is known."""
    if moment.until is None or moment.first or moment.last:
        return None
    through = (moment.number - 1) / moment.count
    if through < 1 / 3:
        return "It's early in the show."
    if through < 2 / 3:
        return "It's about halfway through the show."
    return "The show is into its last part."


def _ago(skipped: int, number: int) -> str:
    if skipped == number - 1:
        return "the last segment"
    if skipped == number - 2:
        return "the segment before last"
    return "an earlier segment"


def brief(
    plan: dict[str, Any],
    moment: Moment,
    material: dict[str, str],
    notes: str,
    said: list[list[Turn]],
    seconds: int,
) -> str:
    """What the writer is told for one segment. Segment numbers stay out of it, so they can't
    end up on air."""
    parts = [moment.clock]
    if moment.until:
        parts.append(f"The show runs until {moment.until}.")
    if where := _where(moment):
        parts.append(where)
    if moment.first:
        parts.append(
            "It opens the show: welcome everyone, say who's on, and in a line what's coming."
        )
    elif moment.straight_on:
        parts.append(
            "It carries straight on from the last segment, with no song between: the first turn "
            "picks up from its last line, mid-conversation. No greeting, and no song to talk about."
        )
    elif moment.before:
        parts.append(
            f"A song has just finished: {moment.before}. They needn't mention it every time; "
            "if they do, it's in the first turn, by whoever speaks first."
        )
    parts.extend(_due(plan, moment.number))
    if moment.move:
        parts.append(
            f"Somewhere in this link, within what it's about, {moment.move}: "
            f"{BY_NAME[moment.move].does}"
        )
    if moment.guest:
        parts.append(
            f"A guest drops in for this segment, in their own voice, and leaves at the end of "
            f"it. Introduce them: {moment.guest}"
        )
    if moment.skipped:
        parts.append(
            f"Listeners didn't hear {_ago(moment.skipped, moment.number)}: someone skipped it. "
            "Don't pay off anything it set up as if they had; set it up again if it's needed."
        )
    if notes:
        parts.append(f"The show's notes so far: {notes}")
    if material:
        parts.append(
            "What's going on today, for reference. Use what this segment is about, and leave the "
            "rest for other segments:\n"
            + "\n\n".join(f"[{name}]\n{text}" for name, text in material.items())
        )
    if said:
        parts.append(
            "What they said in the last segments, oldest first. Carry on from it; don't repeat "
            "it.\n" + "\n\n".join("\n".join(f"{t.speaker}: {t.text}" for t in s) for s in said)
        )
    if moment.last:
        parts.append("It's the show's last segment: pay off anything still running, and sign off.")
    if moment.ends_link and moment.up_next:
        parts.append(f"Songs come back after it. End by bringing in the next one: {moment.up_next}")
        if moment.remarks:
            parts.append(
                "About the songs, to bring up now and then, not every time, and the votes only "
                "as numbers, since nobody knows who voted: " + " ".join(moment.remarks)
            )
    parts.append(
        f"Write about {seconds * PER_SECOND} characters of speech, about {seconds} seconds."
    )
    return "\n\n".join(parts)


async def write_segment(
    ai: AIClient,
    *,
    station: str,
    hosts: list[Host],
    dynamic: str,
    prompt: str,
    plan: dict[str, Any],
    moment: Moment,
    material: dict[str, str],
    notes: str,
    said: list[list[Turn]],
    seconds: int,
) -> tuple[list[Turn], str, list[str]]:
    """A segment's turns, checked, the show's notes after it, and notes on any marks taken
    off. `said` is the show's segments so far, the last few of which the writer reads."""
    instructions = INSTRUCTIONS.format(
        station=station,
        hosts="\n".join(host.described() for host in hosts),
        dynamic=dynamic or "They're old friends.",
        prompt=prompt or "Light chat between the DJs.",
    )
    told = brief(plan, moment, material, notes, said[-SAID_KEPT:], seconds)
    names = [host.name for host in hosts]
    turns, notes = await _written(ai, instructions, told, names)
    if any(_SEGMENT.search(turn.text) for turn in turns):
        # Once more: the plan talks in segments, and a model sometimes copies it.
        turns, notes = await _written(ai, instructions, f"{told}\n\n{AGAIN}", names)
    kept, problems = checked(turns)
    if any(_SEGMENT.search(turn.text) for turn in kept):
        problems.append('It still says "segment" on air.')
    return kept, notes, problems


async def _written(
    ai: AIClient, instructions: str, told: str, names: list[str]
) -> tuple[list[Turn], str]:
    answer = await ai.json(instructions, told, "talk_segment", _schema(names))
    turns = [
        Turn(t["speaker"], t["text"].strip(), t["cut_after"].strip(), t["together"])
        for t in answer["turns"]
        if t["text"].strip() and t["speaker"] in names
    ]
    return turns, answer["notes"].strip()


def _cut_problem(turn: Turn, after: Turn | None, cuts: int) -> str | None:
    """Why `turn` can't be cut where it's marked, if it can't. `after` is the turn after it."""
    at = turn.text.lower().find(turn.cut_after.lower())
    if at < 0:
        return "its words aren't in it"
    if at + len(turn.cut_after) > len(turn.text) - 8:
        return "the words are at its very end"
    if after is None:
        return "it's the last turn"
    if after.speaker == turn.speaker:
        return "the same DJ speaks next"
    if cuts >= MAX_CUTS:
        return f"there are already {MAX_CUTS} cuts"
    return None


def checked(turns: list[Turn]) -> tuple[list[Turn], list[str]]:
    """The turns with any mark that can't work taken off, and notes on what was taken off. A
    cut needs its words in the turn, well before its end, another DJ speaking next, and no more
    than MAX_CUTS in the segment. A turn said together needs another DJ's turn before it, not
    one that's cut off. The turn after a cut starts with an audio tag, [interrupting] if it has
    none."""
    kept: list[Turn] = []
    notes = []
    cuts = 0
    for index, turn in enumerate(turns):
        number = index + 1
        cut, together, text = turn.cut_after, turn.together, turn.text
        if cut:
            after = turns[index + 1] if index + 1 < len(turns) else None
            if problem := _cut_problem(turn, after, cuts):
                notes.append(f"Turn {number} isn't cut: {problem}.")
                cut = ""
            else:
                cuts += 1
        if together:
            before = kept[-1] if kept else None
            if before is None or before.speaker == turn.speaker or before.cut_after:
                notes.append(f"Turn {number} isn't said together with the one before.")
                together = False
        if kept and kept[-1].cut_after and not text.lstrip().startswith("["):
            text = f"[interrupting] {text}"
        kept.append(Turn(turn.speaker, text, cut, together))
    return kept, notes
