"""Writing a talk station's segments: about two minutes of its DJs talking, as turns, for a
segment of a show planned in talk.py.

Each segment is written, then edited: a second pass reads the draft as a listener would, who
knows only what's been said on air, flags anything that doesn't follow or leans on something
never explained, and fixes just that. If the edit can't be had, the draft goes out as it is.

The AI marks where one DJ cuts another off (`cut_after`, the words heard before the next DJ cuts
in) and where two say something at the same moment (`together`). The code checks the marks
rather than trusting them, so a mark that can't work comes off. The turns are voiced one at a
time and mixed so the DJs really talk over each other (mixing.py)."""

import json
import logging
import random
import re
from dataclasses import dataclass, field
from typing import Any

from guildfm.ai import AIClient, AIError, object_schema
from guildfm.talk import Host, does

log = logging.getLogger(__name__)

PER_SECOND = 17  # characters of speech a second, as ElevenLabs' eleven_v4 speaks
KEPT_BY_EDIT = 0.6  # of the draft's characters an edit keeps at least, or it's not used
MAX_CUTS = 2  # interruptions in a segment, so they stay a character trait
SAID_KEPT = 2  # segments before this one the writer reads in full
SONG = ""  # the speaker of the mark, in what was said, for a song that played between segments
# How the segment after a song treats it, dealt in turn: told to name it "now and then", the
# writer named it every time.
MENTIONS = {
    "name": "The first turn says what the song was, in a few words, as a DJ does.",
    "react": (
        "The first turn reacts to the song, as you would to something you've both just heard: "
        'what it brings to mind, or what one of them thinks of it. Not "That was ... by '
        '..."; its title or artist can come up in passing.'
    ),
    "none": "This time they don't mention the song at all.",
}
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

That's a guide, not a checklist: keep to its spirit, but you can reasonably stray from it for \
the sake of variety.

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
- Songs play between some segments, and listeners hear the conversation stop for each one. \
Before a song, they wrap up what they're on: land it, or park it openly to come back to \
("Hold that thought"), never leaving a question or a jab hanging. After one, they come back \
on air, then go back to where they were, saying in a line what it was ("Now, about my \
coat..."), or move on to something new. Never carry on mid-exchange as if no song had played.
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
No segment numbers.

Last, list what this segment told, for the station's log, so no show tells it again for a \
week: each story, fact and joke, a few words each that say which one it was, such as "story: \
the shortbread world champion", "fact: wombats' cube-shaped droppings" or "joke: the peahen \
playing hide-and-seek". Leave out the chat around them."""


EDIT = """You're the editor on {station}, a radio station playing over the speakers in an \
office in the UK. Its DJs talk in segments of about two minutes, and someone else has written \
the next one. Read the draft as a listener would: someone who knows only what's been said on \
air, and may have just walked into the room.

Check it for two things:
1. Does it follow? Each turn should follow from the one before it: answer it, react to it, \
argue with it or build on it. Flag a turn that ignores what was just said, a jump to a new \
topic with no way in, a reply to something nobody said, or a line that makes no sense where it \
is.
Around a song, flag a draft that carries on mid-exchange after a song as if it hadn't played, \
or one that ends before a song on a question or a point left hanging.
2. Is everything explained? Flag a joke or a remark whose premise listeners haven't heard: a \
story riffed on before it's been told, or a person, place, hobby, rivalry, bet or running joke \
mentioned as if listeners knew about it, when it hasn't been said on air in what they've heard.

Then fix what you flagged, and nothing else. Explain a premise where it first comes up, in a \
line or so in the DJ's own voice; add the missing step between two turns; or cut a line that \
can't be saved. Keep every other turn word for word, with its audio tags and its cut_after and \
together marks, and keep it about the same length. Use only what's been said on air and the \
background you're given: never make anything up. Say what each problem was, naming the turn. \
If there's nothing to fix, list no problems and give the turns back as they are."""


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
    move: str | None = None  # the move or feature dealt for this link, on its first segment
    does: str = ""  # what happens in it, if it's one of the show's own features
    feature: bool = False  # the move is one of the show's own features
    mention: str = "name"  # how it treats the song before it, if one played: MENTIONS
    skipped: int | None = None  # a segment listeners didn't hear, skipped by a curator
    until: str | None = None  # when the show ends, in a line-up
    guest: str | None = None  # another DJ dropping in for this segment, as Host.described has them
    # About the song it brings in: its play history, repeat requests and the votes (dj.py).
    remarks: tuple[str, ...] = ()


@dataclass(frozen=True)
class Segment:
    """A segment as written and edited, ready to voice."""

    turns: list[Turn]
    notes: str  # the show's notes after it
    marks: list[str] = field(default_factory=list)  # marks taken off, and why
    fixed: list[str] = field(default_factory=list)  # what the edit found, and fixed
    draft: list[Turn] = field(default_factory=list)  # before the edit, if it changed anything
    told: list[str] = field(default_factory=list)  # each story, fact and joke, in a few words


def _turn_schema(names: list[str]) -> dict[str, Any]:
    return object_schema(
        speaker={"type": "string", "enum": names},
        text={"type": "string"},
        cut_after={"type": "string"},
        together={"type": "boolean"},
    )


def _schema(names: list[str]) -> dict[str, Any]:
    """A segment, as the writer answers: its turns, by DJs named in `names`, and the notes."""
    turns = {"type": "array", "items": _turn_schema(names)}
    told = {"type": "array", "items": {"type": "string"}}
    return object_schema(turns=turns, notes={"type": "string"}, told=told)


def _edit_schema(names: list[str]) -> dict[str, Any]:
    """An edit, as the editor answers: the problems it found first, then the turns, fixed."""
    problems = {"type": "array", "items": {"type": "string"}}
    return object_schema(problems=problems, turns={"type": "array", "items": _turn_schema(names)})


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
    lately: str = "",
) -> str:
    """What the writer is told for one segment. `lately` is what the last week's shows told, a
    line a show (talk.told_lately). Segment numbers stay out of it, so they can't
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
            f"A song has just finished: {moment.before}. The conversation stopped for it, so "
            f"don't pick up mid-exchange as if it hadn't. {MENTIONS[moment.mention]} Then they "
            "go back to where they left off, saying in a line what it was, or move on to "
            "something new."
        )
    parts.extend(_due(plan, moment.number))
    if moment.move and moment.feature:
        parts.append(
            f"This link has one of the show's own features, {moment.move}: {moment.does} Make "
            "room for it: it can take up most of the segment, or come out of what it's about. "
            "Say its name on air, as a show does, so listeners know it's coming round."
        )
    elif moment.move:
        parts.append(
            f"Somewhere in this link, within what it's about, {moment.move}: "
            f"{moment.does or does(moment.move, [])}"
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
    if lately:
        parts.append(
            "The stories, facts and jokes told on air in the last week, today's among them, "
            "oldest first. Listeners have heard these: don't tell any of them again, though a DJ "
            "can call back to one in a line.\n" + lately
        )
    if said:
        parts.append(
            "What they said in the last segments, oldest first, and the songs that played "
            "between. Don't repeat it.\n" + _transcript(said, moment)
        )
    if moment.last:
        parts.append("It's the show's last segment: pay off anything still running, and sign off.")
    if moment.ends_link and moment.up_next:
        parts.append(
            "Songs come back after it, and the conversation stops for the song, so wrap up "
            "first: land what they're on, or park it openly to come back to after the song, "
            "with no question or jab left hanging. End by bringing in the next one: "
            f"{moment.up_next}"
        )
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
    edit: bool = True,
    lately: str = "",
) -> Segment:
    """A segment, written, edited (unless `edit` is False), and with its marks checked. `said`
    is the show's segments so far, the last few of which the writer reads; `lately` is what the
    last week's shows told."""
    instructions = INSTRUCTIONS.format(
        station=station,
        hosts="\n".join(host.described() for host in hosts),
        dynamic=dynamic or "They're old friends.",
        prompt=prompt or "Light chat between the DJs.",
    )
    told = brief(plan, moment, material, notes, said[-SAID_KEPT:], seconds, lately)
    names = [host.name for host in hosts]
    turns, after, items = await _written(ai, instructions, told, names)
    if any(_SEGMENT.search(turn.text) for turn in turns):
        # Once more: the plan talks in segments, and a model sometimes copies it.
        turns, after, items = await _written(ai, instructions, f"{told}\n\n{AGAIN}", names)
    draft, fixed = turns, []
    if edit and turns:
        turns, fixed = await _edited(
            ai, station, hosts, dynamic, plan, moment, material, notes, said[-SAID_KEPT:], turns
        )
    kept, marks = checked(turns)
    if any(_SEGMENT.search(turn.text) for turn in kept):
        marks.append('It still says "segment" on air.')
    return Segment(kept, after, marks, fixed, draft if fixed else [], items)


async def _written(
    ai: AIClient, instructions: str, told: str, names: list[str]
) -> tuple[list[Turn], str, list[str]]:
    """The turns, the show's notes, and what the segment told."""
    answer = await ai.json(instructions, told, "talk_segment", _schema(names))
    items = [str(item).strip() for item in answer.get("told", []) if str(item).strip()]
    return _turns(answer["turns"], names), answer["notes"].strip(), items


def _turns(answered: list[dict[str, Any]], names: list[str]) -> list[Turn]:
    return [
        Turn(t["speaker"], t["text"].strip(), t["cut_after"].strip(), t["together"])
        for t in answered
        if t["text"].strip() and t["speaker"] in names
    ]


def heard(moment: Moment, notes: str, said: list[list[Turn]]) -> str:
    """What listeners have heard before a segment, as the editor is told it."""
    parts = []
    if moment.first:
        parts.append("This segment opens the show: listeners haven't heard these DJs yet today.")
    elif moment.straight_on:
        parts.append("It carries straight on from the last segment, with no song between.")
    elif moment.before:
        parts.append(f"A song has just finished: {moment.before}.")
    if notes and not moment.first:
        parts.append(f"Earlier in the show, as the show's notes have it: {notes}")
    if said and not moment.first:
        parts.append(
            "The last segments, word for word, oldest first, and the songs that played "
            "between:\n" + _transcript(said, moment)
        )
    return "\n\n".join(parts)


def deal_mention(rng: random.Random, last: str | None, move: str | None) -> str:
    """How the segment after a song treats it: never the same way twice in a row, and a
    reaction when the move is to rate it."""
    if move == "the verdict":
        return "react"
    return rng.choice([mention for mention in MENTIONS if mention != last])


def _after_song(moment: Moment) -> bool:
    """Whether a song played between the segment before and this one."""
    return bool(moment.before) and not moment.straight_on


def remembered(moment: Moment, turns: list[Turn]) -> list[Turn]:
    """A segment as it's kept for those after it: its turns, after a mark for the song that
    played before it, if one did."""
    return [Turn(SONG, moment.before or ""), *turns] if _after_song(moment) else turns


def _transcript(said: list[list[Turn]], moment: Moment) -> str:
    """What was said lately, oldest first, with the songs that played between, up to the one
    that has just finished before this segment."""
    lines = [
        "\n".join(
            f"[A song played: {t.text}]" if t.speaker == SONG else f"{t.speaker}: {t.text}"
            for t in segment
        )
        for segment in said
    ]
    if _after_song(moment):
        lines.append(f"[A song played: {moment.before}. It has just finished.]")
    return "\n\n".join(lines)


def _background(
    hosts: list[Host],
    dynamic: str,
    plan: dict[str, Any],
    moment: Moment,
    material: dict[str, str],
) -> str:
    parts = [
        "The DJs:\n" + "\n".join(host.described() for host in hosts),
        f"How they get on: {dynamic or 'They are old friends.'}",
        *_due(plan, moment.number),
    ]
    if material:
        parts.append(
            "What's going on today:\n"
            + "\n\n".join(f"[{name}]\n{text}" for name, text in material.items())
        )
    return "\n\n".join(parts)


async def _edited(
    ai: AIClient,
    station: str,
    hosts: list[Host],
    dynamic: str,
    plan: dict[str, Any],
    moment: Moment,
    material: dict[str, str],
    notes: str,
    said: list[list[Turn]],
    turns: list[Turn],
) -> tuple[list[Turn], list[str]]:
    """The turns, edited for listeners, and what the edit found. The draft as it was if the edit
    couldn't be had, or came back with too little of it."""
    draft = [
        {"speaker": t.speaker, "text": t.text, "cut_after": t.cut_after, "together": t.together}
        for t in turns
    ]
    prompt = "\n\n".join(
        [
            # The day and time, or it guesses them, and "fixes" a line that has them right.
            moment.clock,
            "WHAT LISTENERS HAVE HEARD\n\n" + (heard(moment, notes, said) or "Nothing yet."),
            "BACKGROUND, which listeners know only if it's been said on air\n\n"
            + _background(hosts, dynamic, plan, moment, material),
            *(
                [f"After the draft, a song plays: {moment.up_next}"]
                if moment.ends_link and moment.up_next
                else []
            ),
            "The draft:\n" + json.dumps(draft, ensure_ascii=False, indent=1),
        ]
    )
    names = [host.name for host in hosts]
    try:
        answer = await ai.json(
            EDIT.format(station=station), prompt, "talk_edit", _edit_schema(names)
        )
    except AIError as error:
        log.warning("A segment went out unedited: %s", error)
        return turns, []
    problems = [problem.strip() for problem in answer["problems"] if problem.strip()]
    edited = _turns(answer["turns"], names)
    if not problems:
        return turns, []
    if sum(len(t.text) for t in edited) < KEPT_BY_EDIT * sum(len(t.text) for t in turns):
        log.warning("A segment's edit cut too much of it, so it went out as written")
        return turns, []
    return edited, problems


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
