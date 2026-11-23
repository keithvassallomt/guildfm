"""Talk stations: shows that are mostly their DJs talking, from a script prompt. See talk.md.

A show is planned when it starts: the whole show in a line-up, an hour at a time outside one.
Its talk comes in segments of two minutes at most, the most that's written and voiced in time.
The code deals the show one or two running bits from the banter moves, and rolls the dice for a
happening; the AI then plans what each segment is about and places the bits' setups and
payoffs across them. The code deals the moves, not the AI: left to itself, a model picks the
same favourites every time.

The code also deals each DJ one or two of their hooks for the show, resting the ones they had
last time: left to itself, the AI brings every hook into every show, and the same few stories
come round each day. The plan is kept with the show's state in the source's dj_memory. Each
show goes in a short log on the station, with its running bits, what it talked about and the
hooks it had, so a daily show doesn't repeat itself and can call back."""

import math
import random
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from guildfm.ai import AIClient, object_schema
from guildfm.models import DJProfile

SEGMENT_SECONDS = 120  # talk written and voiced in one go, at most
LONGEST = 30 * 60  # seconds of talk between two songs at most
SONG_SECONDS = 210  # a song, about, for sizing links
HAPPENING_CHANCE = 0.4  # of a show having a happening
SHOWS_KEPT = 60  # shows kept in a station's log: a week's, outside a line-up an hour is one
TOPIC_DAYS = 7  # days of shows whose topics the planner is shown: [news] goes back a week
BITS_SHOWN = 6  # recent shows whose running bits the planner is shown, for calling back to
HOOKS = ("pet_peeves", "soft_spots", "obsession")  # a DJ's hooks, as Host has them
MOVES_KEPT = 2  # a link's move is never one of the last this many


@dataclass(frozen=True)
class Move:
    """Something for the DJs to do, rather than just "be funny"."""

    name: str
    does: str  # what happens, for the AI
    running: bool = False  # set up early in a show and paid off later
    needs: tuple[str, ...] = ()  # hooks one of the DJs needs at least one of
    guest: bool = False  # another DJ drops in
    after_song: bool = False  # only for talk that follows a song


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
        "A running quiz between them, such as guessing a number from the day's news before "
        "it's revealed. The score carries through the show.",
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
    Move("the verdict", "Both rate the last song, and disagree.", after_song=True),
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


def deal_bits(rng: random.Random, log: list[dict[str, Any]]) -> list[str]:
    """The running bits for a show: one or two, leaving out the last two the station's shows
    used if there's anything else."""
    running = [move.name for move in MOVES if move.running]
    lately = {bit["move"] for bit in [b for show in log for b in show["bits"]][-2:]}
    fresh = [name for name in running if name not in lately] or running
    return rng.sample(fresh, min(len(fresh), rng.choice((1, 2))))


def deal_hooks(
    rng: random.Random, hosts: list[Host], log: list[dict[str, Any]]
) -> dict[str, list[str]]:
    """Which of each DJ's hooks a show has, by name: one or two of those they have, resting the
    ones they had in the station's last show if there are others."""
    last = log[-1].get("hooks", {}) if log else {}
    dealt = {}
    for host in hosts:
        have = [hook for hook in HOOKS if getattr(host, hook)]
        if not have:
            continue
        fresh = [hook for hook in have if hook not in last.get(host.name, [])] or have
        chosen = rng.sample(fresh, min(len(fresh), rng.choice((1, 2))))
        dealt[host.name] = [hook for hook in HOOKS if hook in chosen]
    return dealt


def with_hooks(hosts: list[Host], hooks: dict[str, list[str]] | None) -> list[Host]:
    """The DJs with only the hooks dealt to the show. All of them for a plan made before hooks
    were dealt, which has None."""
    if hooks is None:
        return hosts
    return [
        replace(host, **{hook: "" for hook in HOOKS if hook not in hooks.get(host.name, [])})
        for host in hosts
    ]


def deal_move(
    rng: random.Random, hosts: list[Host], guests: bool, last: list[str], song: bool = True
) -> str:
    """A move for one link: not a running bit, one the DJs have the hooks for, a guest only if
    there's another DJ to drop in, one about the last song only if one just played (`song`),
    and none of the last few."""
    allowed = [
        move.name
        for move in MOVES
        if not move.running
        and _hooked(move, hosts)
        and (guests or not move.guest)
        and (song or not move.after_song)
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


def segment_lengths(ratio: int) -> list[int]:
    """How long each segment of a link runs, in seconds, at `ratio` percent talk: never more
    than two minutes. The first is made while the song before it plays, in the 90 seconds the
    song is lined up ahead (less when the station crossfades), and a longer one can't be: at
    the office a three-minute segment took 83 seconds to write and voice, and its song started
    first. At 100%, the only songs are requests, and a request's link is one segment bringing
    it in."""
    if ratio >= 100:
        return [SEGMENT_SECONDS]
    total = min(link_seconds(ratio) or LONGEST, LONGEST)
    count = math.ceil(total / SEGMENT_SECONDS)
    return [round(total / count)] * count


def segment_count(minutes: int, ratio: int) -> int:
    """How many segments of talk a show of `minutes` has at `ratio` percent talk."""
    return max(1, round(minutes * 60 * ratio / 100 / segment_lengths(ratio)[0]))


PLAN_INSTRUCTIONS = (
    "You plan the talk on {station}, a radio station playing over the speakers in an office in "
    "the UK. This show is mostly talk: its DJs chat, bicker and banter, with songs in between. "
    "Plan it, don't write it: someone else writes what they say, a segment at a time.\n\n"
    "The DJs:\n{hosts}\n\nHow they get on: {dynamic}\n\n"
    "What the show is about, in its producer's words:\n{prompt}\n\n"
    "That's a guide, not a checklist. Keep to its spirit, but stray from it where it makes for "
    "a more varied show: not every show needs everything in it, and the DJs can take in things "
    "it doesn't mention."
)
PLAN = object_schema(
    segments={
        "type": "array",
        "items": object_schema(about={"type": "string"}, topic={"type": "string"}),
    },
    bits={
        "type": "array",
        "items": object_schema(
            move={"type": "string"},
            idea={"type": "string"},
            ending={"type": "string"},
            setup={"type": "integer"},
            payoff={"type": "integer"},
        ),
    },
    happening=object_schema(
        idea={"type": "string"},
        ending={"type": "string"},
        starts={"type": "integer"},
        ends={"type": "integer"},
    ),
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
    log: list[dict[str, Any]],
    until: str | None = None,
) -> dict[str, Any]:
    """A show's plan: what each segment is about, and where its running bits and happening
    fall. `until` is when a show in a line-up ends, such as "13:00"; without it, the plan is
    for the next `minutes`, with more to come. `log` is the station's last few shows: their
    running bits and what they talked about. `hosts` have the hooks dealt to the show. The plan
    names each segment's topic, for the log. Setups and payoffs that don't fit the show are
    moved so they do, and a bit the AI made up beyond those dealt is dropped."""
    count = segment_count(minutes, ratio)
    parts = [f"It's {starts:%A} {starts.day} {starts:%B}, {starts:%H:%M}."]
    if until:
        parts.append(f"The show runs until {until}: {count} segments of talk.")
    else:
        parts.append(f"This plans the next {minutes} minutes of the show: {count} segments.")
    parts.append(
        f"Each segment is up to two minutes of talk, numbered 1 to {count}. "
        + ("There are no songs: the talk runs on." if ratio >= 100 else "Songs play between them.")
    )
    parts.append(
        "Plan it so that someone listening can follow it. Give each segment one topic, two at "
        "most, with room to tell it and argue about it. Spread what's going on across the show; "
        "it doesn't all have to be used. Listeners know only what's said on air, so the first "
        "segment to bring up one of a DJ's hooks, such as a hobby or a rival, explains it. "
        'Name each segment\'s topic in a few words, such as "the goat elected mayor" or '
        "\"the stolen garden gnome\": it goes in the station's log, so later shows know what's "
        "been covered."
    )
    if material:
        parts.append(
            "What's going on, for the segments to draw on:\n"
            + "\n\n".join(f"[{name}]\n{text}" for name, text in material.items())
        )
    if "news" in material:
        parts.append(
            "The news goes back a week, newest first: favour the newest stories, and leave out "
            "any the last week's shows have had."
        )
    dealt = "\n".join(f"- {name}: {BY_NAME[name].does}" for name in bits)
    parts.append(
        f"This show's running bits, one each:\n{dealt}\nMake each one specific to these DJs, "
        "and simple enough to explain in a line. Set it up early, bring it back once in between "
        "at most, and pay it off at least two segments later, before the last segment. Its idea "
        "is what it is and what's at stake; its ending is how it pays off, which the DJs only "
        "learn when it's due. A quiz or a bet with an answer takes the answer from what's going "
        "on, given here: never from facts about songs or anything else you haven't been given."
    )
    if happening:
        parts.append(
            f"This show has a happening, {happening}: {HAPPENINGS[happening]} It isn't in the "
            "producer's words. Say what it is, the segment it starts in and the one it comes to "
            "a head in, and how it ends."
        )
    else:
        parts.append("This show has no happening: leave the happening's idea empty.")
    bits_lately = [(show["on"], bit) for show in log[-BITS_SHOWN:] for bit in show["bits"]]
    if bits_lately:
        parts.append(
            "Running bits from the last few shows, oldest first. Don't repeat them, but you can "
            "call back to one:\n"
            + "\n".join(f"- {on}: {bit['move']}, {bit['idea']}" for on, bit in bits_lately)
        )
    week = (starts.date() - timedelta(days=TOPIC_DAYS)).isoformat()
    covered = [(show["on"], show["topics"]) for show in log if show["on"] >= week]
    covered = [(on, topics) for on, topics in covered if topics]
    if covered:
        parts.append(
            "What the last week's shows talked about, oldest first. Listeners have heard these, "
            "so don't plan them again, and don't retell a story from the news they've had. A "
            "DJ's hook can come back, with something new about it:\n"
            + "\n".join(f"- {on}: {'; '.join(topics)}" for on, topics in covered)
        )
    parts.append(
        "No politics, religion or tragedy, and no made-up facts about real people or songs. "
        "The DJs never mention segments on air, so in what you write, never refer to one by "
        'its number: say "later" or "next time". The numbers go in setup, payoff and starts.'
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
    named = [s.get("topic", "").strip() for s in answer["segments"]][:count]
    topics = list(dict.fromkeys(topic for topic in named if topic))
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
        placed.append(
            {
                "move": name,
                "idea": bit["idea"].strip(),
                "ending": bit["ending"].strip(),
                "setup": setup,
                "payoff": payoff,
            }
        )
    answered_happening = answer["happening"]
    idea = answered_happening["idea"].strip()
    surprise = None
    if happening and idea:
        start = min(max(1, answered_happening["starts"]), count)
        surprise = {
            "kind": happening,
            "idea": idea,
            "ending": answered_happening["ending"].strip(),
            "starts": start,
            "ends": min(max(start, answered_happening["ends"]), count),
        }
    return {"segments": segments, "topics": topics, "bits": placed, "happening": surprise}


def _same(said: str, name: str) -> bool:
    """Whether the AI's name for a move, such as "Bet", is `name`, "the bet"."""
    said = said.strip().lower()
    return said in (name, name.removeprefix("the "))


def _dealt(said: str, names: list[str]) -> bool:
    return any(_same(said, name) for name in names)


def logged(log: list[dict[str, Any]], plan: dict[str, Any], day: str) -> list[dict[str, Any]]:
    """The station's log with a show added, keeping the last few: its running bits with how
    they ended, for calling back to, what it talked about, and the hooks it had."""
    show = {
        "on": day,
        "bits": [
            {"move": bit["move"], "idea": f"{bit['idea']} {bit.get('ending', '')}".strip()}
            for bit in plan["bits"]
        ],
        "topics": plan.get("topics", []),
        "hooks": plan.get("hooks", {}),
    }
    return [*log, show][-SHOWS_KEPT:]
