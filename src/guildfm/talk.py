"""Talk stations: shows that are mostly their DJs talking, from a script prompt. See talk.md.

A show is planned when it starts: the whole show in a line-up, an hour at a time outside one.
Its talk comes in segments of about two minutes, the most that's written and voiced in one go.
The code deals the show one or two running bits from the banter moves, and rolls the dice for a
happening; the AI then plans what each segment is about and places the bits' setups and
payoffs across them. The code deals the moves, not the AI: left to itself, a model picks the
same favourites every time.

The plan is kept with the show's state in the source's dj_memory. Each show's running bits go
in a short log on the station, so a daily show doesn't repeat itself and can call back."""

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from guildfm.ai import AIClient, object_schema
from guildfm.models import DJProfile

SEGMENT_SECONDS = 120  # talk written and voiced in one go
SONG_SECONDS = 210  # a song, about, for sizing links
HAPPENING_CHANCE = 0.4  # of a show having a happening
LOG_KEPT = 12  # running bits kept in a station's log
MOVES_KEPT = 2  # a link's move is never one of the last this many


@dataclass(frozen=True)
class Move:
    """Something for the DJs to do, rather than just "be funny"."""

    name: str
    does: str  # what happens, for the AI
    running: bool = False  # set up early in a show and paid off later
    needs: tuple[str, ...] = ()  # hooks one of the DJs needs at least one of
    guest: bool = False  # another DJ drops in


MOVES = (
    Move(
        "the bet",
        "Stakes are set early and settled later. The loser pays up on air, or refuses to.",
        running=True,
    ),
    Move(
        "the challenge",
        "One DJ sets the other a task, such as talking about the weather without saying "
        '"rain", or sneaking a word into a later link. It pays off later.',
        running=True,
    ),
    Move(
        "the score",
        "A running quiz between them, such as guessing the year of the next song before it's "
        "announced. The score carries through the show.",
        running=True,
    ),
    Move(
        "the correction",
        "One DJ says something and the other corrects them, from what they've been given (the "
        "news, the play history), never from invented trivia.",
    ),
    Move(
        "the wind-up", "One DJ deliberately pokes at the other's pet peeve.", needs=("pet_peeves",)
    ),
    Move("the verdict", "Both rate the last song, and disagree."),
    Move(
        "the confession",
        "One DJ admits something embarrassing about themselves, made up and harmless, from "
        "their soft spots or what they keep coming back to.",
        needs=("soft_spots", "obsession"),
    ),
    Move("the aside", "One DJ whispers to the listeners behind the other's back."),
    Move("the producer", "Both complain about their producer, who's never heard."),
    Move("the guest", "Another of GuildFM's DJs drops in, in their own voice.", guest=True),
)
BY_NAME = {move.name: move for move in MOVES}

# Something unexpected between the DJs, not in the script prompt.
HAPPENINGS = {
    "an argument": "An argument about something trivial or personal, never anything "
    "controversial, that flares up and is made up again.",
    "a prank": "One DJ plays a prank on the other: a practical joke, or a funny dare.",
    "a bet": "A bet nobody planned, made in the heat of the moment and settled before the end.",
    "a surprise guest": "Another of GuildFM's DJs drops in unannounced, in their own voice.",
}


@dataclass(frozen=True)
class Host:
    """A DJ on a talk station, as the AI is told about them."""

    name: str
    personality: str
    pet_peeves: str = ""
    soft_spots: str = ""
    obsession: str = ""

    @classmethod
    def of(cls, dj: DJProfile) -> Host:
        return cls(dj.name, dj.personality, dj.pet_peeves, dj.soft_spots, dj.obsession)

    def described(self) -> str:
        parts = [f"{self.name}: {self.personality or 'no personality given.'}"]
        if self.pet_peeves:
            parts.append(f"Pet peeves: {self.pet_peeves}")
        if self.soft_spots:
            parts.append(f"Soft spots: {self.soft_spots}")
        if self.obsession:
            parts.append(f"Keeps coming back to: {self.obsession}")
        return " ".join(parts)


def talks(station) -> bool:
    """Whether `station` is a talk station that can talk: two or more DJs, each with an
    ElevenLabs voice. Otherwise its first DJ, if any, talks between songs as usual."""
    hosts = station.hosts
    return bool(
        station.talk_station
        and len(hosts) >= 2
        and all(dj.voice.startswith("elevenlabs:") for dj in hosts)
    )


def all_talk(station) -> bool:
    """Whether `station` is a talk station at 100% talk: it picks no songs of its own."""
    return talks(station) and station.talk_ratio >= 100


def _hooked(move: Move, hosts: list[Host]) -> bool:
    return not move.needs or any(getattr(host, hook) for host in hosts for hook in move.needs)


def deal_bits(rng: random.Random, log: list[dict[str, str]]) -> list[str]:
    """The running bits for a show: one or two, leaving out the moves its last show used if
    there's anything else."""
    running = [move.name for move in MOVES if move.running]
    lately = {bit["move"] for bit in log[-2:]}
    fresh = [name for name in running if name not in lately] or running
    return rng.sample(fresh, min(len(fresh), rng.choice((1, 2))))


def deal_move(rng: random.Random, hosts: list[Host], guests: bool, last: list[str]) -> str:
    """A move for one link: not a running bit, one the DJs have the hooks for, a guest only if
    there's another DJ to drop in, and none of the last few."""
    allowed = [
        move.name
        for move in MOVES
        if not move.running and _hooked(move, hosts) and (guests or not move.guest)
    ]
    fresh = [name for name in allowed if name not in last[-MOVES_KEPT:]] or allowed
    return rng.choice(fresh)


def roll_happening(rng: random.Random, guests: bool) -> str | None:
    """Whether a show has a happening, four times in ten, and which."""
    if rng.random() >= HAPPENING_CHANCE:
        return None
    kinds = [kind for kind in HAPPENINGS if guests or kind != "a surprise guest"]
    return rng.choice(kinds)


def link_seconds(ratio: int) -> int | None:
    """How long the talk between two songs runs, so that talk is `ratio` percent of the time.
    None at 100%: there are no songs, and the talk runs on."""
    if ratio >= 100:
        return None
    return round(SONG_SECONDS * ratio / (100 - ratio))


def segment_count(minutes: int, ratio: int) -> int:
    """How many segments of talk a show of `minutes` has at `ratio` percent talk."""
    return max(1, round(minutes * 60 * ratio / 100 / SEGMENT_SECONDS))


PLAN_INSTRUCTIONS = (
    "You plan the talk on {station}, a radio station playing over the speakers in an office in "
    "the UK. This show is mostly talk: its DJs chat, bicker and banter, with songs in between. "
    "Plan it, don't write it: someone else writes what they say, a segment at a time.\n\n"
    "The DJs:\n{hosts}\n\nHow they get on: {dynamic}\n\n"
    "What the show is about, in its producer's words:\n{prompt}"
)
PLAN = object_schema(
    segments={
        "type": "array",
        "items": object_schema(about={"type": "string"}),
    },
    bits={
        "type": "array",
        "items": object_schema(
            move={"type": "string"},
            idea={"type": "string"},
            setup={"type": "integer"},
            payoff={"type": "integer"},
        ),
    },
    happening=object_schema(idea={"type": "string"}, starts={"type": "integer"}),
)


async def plan_show(
    ai: AIClient,
    *,
    station: str,
    hosts: list[Host],
    dynamic: str,
    prompt: str,
    material: dict[str, str],
    starts: datetime,
    minutes: int,
    ratio: int,
    bits: list[str],
    happening: str | None,
    log: list[dict[str, str]],
    until: str | None = None,
) -> dict[str, Any]:
    """A show's plan: what each segment is about, and where its running bits and happening
    fall. `until` is when a show in a line-up ends, such as "13:00"; without it, the plan is
    for the next `minutes`, with more to come. `log` is the station's running bits from its
    last few shows. Setups and payoffs that don't fit the show are moved so they do, and a bit
    the AI made up beyond those dealt is dropped."""
    count = segment_count(minutes, ratio)
    parts = [f"It's {starts:%A} {starts.day} {starts:%B}, {starts:%H:%M}."]
    if until:
        parts.append(f"The show runs until {until}: {count} segments of talk.")
    else:
        parts.append(f"This plans the next {minutes} minutes of the show: {count} segments.")
    parts.append(
        f"Each segment is about two minutes of talk, numbered 1 to {count}. "
        + ("There are no songs: the talk runs on." if ratio >= 100 else "Songs play between them.")
    )
    if material:
        parts.append(
            "What's going on, for the segments to draw on:\n"
            + "\n\n".join(f"[{name}]\n{text}" for name, text in material.items())
        )
    dealt = "\n".join(f"- {name}: {BY_NAME[name].does}" for name in bits)
    parts.append(
        f"This show's running bits, one each:\n{dealt}\nMake each one specific to these DJs. Set "
        "it up early, let it come back in between, and pay it off at least two segments later, "
        "before the last segment."
    )
    if happening:
        parts.append(
            f"This show has a happening, {happening}: {HAPPENINGS[happening]} It isn't in the "
            "producer's words. Say what it is and the segment it starts in."
        )
    else:
        parts.append("This show has no happening: leave the happening's idea empty.")
    if log:
        parts.append(
            "Running bits from the last few shows, oldest first. Don't repeat them, but you can "
            "call back to one:\n" + "\n".join(f"- {b['on']}: {b['move']}, {b['idea']}" for b in log)
        )
    parts.append(
        "No politics, religion or tragedy, and no made-up facts about real people or songs. "
        "The segments' numbers are for planning: the DJs never say them on air."
    )
    instructions = PLAN_INSTRUCTIONS.format(
        station=station,
        hosts="\n".join(host.described() for host in hosts),
        dynamic=dynamic or "They're old friends.",
        prompt=prompt or "Light chat between the DJs.",
    )
    answer = await ai.json(instructions, "\n\n".join(parts), "show_plan", PLAN)

    segments = [s["about"].strip() for s in answer["segments"]][:count]
    segments += ["Whatever comes up."] * (count - len(segments))
    placed = []
    last = max(1, count - 1)  # paid off before the last segment, if there's room
    answered = list(answer["bits"])
    for name in bits:
        # The AI's plan for this bit, by its name, or else the next it gave.
        bit = next((b for b in answered if _same(b["move"], name)), None)
        bit = bit or next((b for b in answered if not _dealt(b["move"], bits)), None)
        if bit is None:
            continue
        answered.remove(bit)
        setup = min(max(1, bit["setup"]), max(1, last - 2))
        payoff = max(setup, min(max(bit["payoff"], setup + 2), last))
        placed.append({"move": name, "idea": bit["idea"].strip(), "setup": setup, "payoff": payoff})
    idea = answer["happening"]["idea"].strip()
    surprise = None
    if happening and idea:
        start = min(max(1, answer["happening"]["starts"]), count)
        surprise = {"kind": happening, "idea": idea, "starts": start}
    return {"segments": segments, "bits": placed, "happening": surprise}


def _same(said: str, name: str) -> bool:
    """Whether the AI's name for a move, such as "Bet", is `name`, "the bet"."""
    said = said.strip().lower()
    return said in (name, name.removeprefix("the "))


def _dealt(said: str, names: list[str]) -> bool:
    return any(_same(said, name) for name in names)


def logged(log: list[dict[str, str]], plan: dict[str, Any], day: str) -> list[dict[str, str]]:
    """The station's log with a show's running bits added, keeping the last few."""
    added = [{"on": day, "move": bit["move"], "idea": bit["idea"]} for bit in plan["bits"]]
    return [*log, *added][-LOG_KEPT:]
