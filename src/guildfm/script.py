"""Writing a talk station's segments: about two minutes of its DJs talking, as turns, for a
segment of a show planned in talk.py.

The AI marks where one DJ cuts another off (`cut_after`, the words heard before the next DJ cuts
in) and where two say something at the same moment (`together`). The code checks the marks
rather than trusting them, so a mark that can't work comes off. The turns are voiced one at a
time and mixed so the DJs really talk over each other (mixing.py)."""

from dataclasses import dataclass
from typing import Any

from guildfm.ai import AIClient, object_schema
from guildfm.talk import BY_NAME, Host

PER_SECOND = 17  # characters of speech a second, as ElevenLabs' eleven_v4 speaks
MAX_CUTS = 2  # interruptions in a segment, so they stay a character trait
SAID_KEPT = 2  # segments before this one the writer reads in full

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
segment, such as the score, the stakes, and who owes whom."""


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
    before: str | None = None  # the song that just played, such as '"Dreams" by Fleetwood Mac'
    up_next: str | None = None  # the song it brings in, with any shout-out, at the link's end
    move: str | None = None  # the move dealt for this link, on its first segment
    skipped: int | None = None  # a segment listeners didn't hear, skipped by a curator
    until: str | None = None  # when the show ends, in a line-up


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
    """What the plan has for segment `number`: its subject, and the bits and happening due."""
    lines = []
    if 0 < number <= len(plan["segments"]):
        lines.append(f"This segment is about: {plan['segments'][number - 1]}")
    for bit in plan["bits"]:
        if bit["setup"] == number:
            lines.append(f"Set up {bit['move']} now: {bit['idea']}")
        elif bit["payoff"] == number:
            lines.append(f"Pay off {bit['move']} now: {bit['idea']}")
        elif bit["setup"] < number < bit["payoff"]:
            lines.append(f"{bit['move']} is running ({bit['idea']}): bring it up if it fits.")
    happening = plan.get("happening")
    if happening and happening["starts"] == number:
        lines.append(f"The happening, {happening['kind']}, starts now: {happening['idea']}")
    elif happening and happening["starts"] < number:
        lines.append(f"The happening, {happening['kind']}, is under way: {happening['idea']}")
    return lines


def brief(
    plan: dict[str, Any],
    moment: Moment,
    material: dict[str, str],
    notes: str,
    said: list[list[Turn]],
    seconds: int,
) -> str:
    """What the writer is told for one segment."""
    parts = [moment.clock]
    if moment.until:
        parts.append(f"The show runs until {moment.until}.")
    parts.append(f"This is segment {moment.number} of {moment.count}.")
    if moment.first:
        parts.append("It opens the show: welcome everyone, and say who's on and what's coming.")
    if moment.before:
        parts.append(f"Just played: {moment.before}.")
    parts.extend(_due(plan, moment.number))
    if moment.move:
        parts.append(f"Somewhere in this link, {moment.move}: {BY_NAME[moment.move].does}")
    if moment.skipped:
        parts.append(
            f"Listeners didn't hear segment {moment.skipped}: someone skipped it. Don't pay off "
            "anything it set up as if they had; set it up again if it's needed."
        )
    if notes:
        parts.append(f"The show's notes so far: {notes}")
    if material:
        parts.append(
            "What's going on, to draw on:\n"
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
    answer = await ai.json(instructions, told, "talk_segment", _schema(names))
    turns = [
        Turn(t["speaker"], t["text"].strip(), t["cut_after"].strip(), t["together"])
        for t in answer["turns"]
        if t["text"].strip() and t["speaker"] in names
    ]
    kept, problems = checked(turns)
    return kept, answer["notes"].strip(), problems


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
