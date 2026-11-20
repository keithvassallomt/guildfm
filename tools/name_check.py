"""Measures the display-name check (Stage 22 in dev.md): asks OpenAI about each name several
times, with today's wording and the new one, and says how often each was turned down.

    uv run python -m tools.name_check [--times 5] [--asks 1] [--office names.txt]

`--asks 3` measures asking three times at once and turning a name down if any answer does.
`--office` adds a file of the office's display names, one a line ("id|name" is fine, as
sqlite3 prints them), to those that must stay fine. They're read from the file rather than kept
here, as they're real people's names. Real calls, so it costs a little: a call is about a
thousand tokens."""

import argparse
import asyncio
import time
from collections import Counter
from pathlib import Path

from guildfm import names
from guildfm.ai import AIClient, AIError, object_schema
from guildfm.config import get_settings

# The wording before Stage 22, for comparison.
TODAY = """\
You check a name someone picked for themselves in an office jukebox app. Everyone in the office \
sees it beside the songs they request. The input is the name and nothing else.

Answer "vulgar" for anything rude, sexual, crude or offensive, in any language, including \
disguised spellings and words run together, such as "bigballs" or "fucktard".

Answer "not_a_name" for anything that isn't plausibly what a person is called: an ordinary \
word, a made-up word, a phrase or gibberish, such as "bungalistic", "pizza" or "asdfgh".

Otherwise answer "fine". First names, surnames, full names, initials, short forms and everyday \
nicknames from any culture are fine, in any capitals, such as "Dan Jackson", "ricky", "JP", \
"Mo", "Big Mike" or "Siobhán". A username can add digits or join parts of a name, such as \
"hatkinson101" or "keithv"."""
TODAY_VERDICT = object_schema(verdict={"type": "string", "enum": ["fine", "vulgar", "not_a_name"]})

# Names with a description added: each must be turned down every time.
DESCRIBED = [
    # Dev.md's table.
    "Gary from Nottingham",
    "GARY FROM NOTTINGHAM",
    "Gary from Nottigham",
    "GARY FROM NOTTIGHAM",
    "Sam in Accounts",
    # The rule's examples, written differently.
    "gary from nottingham",
    "Gary  from  Nottingham",
    "Dave the plumber",
    "DAVE THE PLUMBER",
    "Priya (marketing)",
    "Sam in acounts",
    # Not among the rule's examples.
    "Chris from Facilities",
    "Emma in Reception",
    "Mo from Manchester",
    "Steve the IT guy",
    "Jo (Design team)",
    "Bob, Accounts",
    "Rachel - Leeds office",
    "Gaz from Notts",
    "Paul at the warehouse",
    "Dr Patel from Finance",
    "Helen, Office Manager",
    "Tony the boss",
    "KEITH FROM MALTA",
    "Jenny from the block",
]

# Real names and nicknames: each must be allowed every time.
FINE = [
    "Gary Nottingham",
    "Ahmed bin Rashid",
    "Jan van der Berg",
    "Leonardo da Vinci",
    "Maria dos Santos",
    "Big Mike",
    "Little Jo",
    "Dan Jackson",
    "ricky",
    "JP",
    "Mo",
    "Siobhán",
    "Mary-Kate O'Brien",
    "Abdul Rahman",
    "Pieter de Vries",
    "Ludwig van Beethoven",
    "Fatima Al-Sayed",
    "Chris Townsend",
    "Jack London",
    "Paris Hilton",
]

# Turned down as before: not names at all, or rude.
STILL_NOT = ["bungalistic", "pizza", "asdfgh", "BigBalls", "fucktard"]

# Of several answers, the one that decides: any that isn't fine turns the name down.
WORST = ["vulgar", "described", "not_a_name", "fine"]


async def trial(ai: AIClient, instructions: str, schema: dict, name: str, asks: int) -> str:
    """One go at checking `name`: `asks` answers at once, the worst of them winning."""
    try:
        answers = await asyncio.gather(
            *(ai.json(instructions, name, "name_check", schema) for _ in range(asks))
        )
    except AIError as error:
        return f"error ({error})"
    found = [str(answer.get("verdict")) for answer in answers]
    return min(found, key=lambda verdict: WORST.index(verdict) if verdict in WORST else -1)


async def measure(
    ai: AIClient, instructions: str, schema: dict, every: list[str], times: int, asks: int
) -> dict[str, Counter]:
    gate = asyncio.Semaphore(12)

    async def one(name: str) -> tuple[str, str]:
        async with gate:
            return name, await trial(ai, instructions, schema, name, asks)

    results: dict[str, Counter] = {name: Counter() for name in every}
    for name, verdict in await asyncio.gather(*(one(n) for n in every for _ in range(times))):
        results[name][verdict] += 1
    return results


def office_names(path: Path) -> list[str]:
    found = []
    for line in path.read_text().splitlines():
        name = line.split("|", 1)[-1].strip()
        if name:
            found.append(name)
    return found


def show(title: str, group: list[str], today: dict, new: dict, times: int, want_down: bool) -> bool:
    """Prints the group's table, and whether the new wording got every name right every time."""
    print(f"\n{title}")
    print(f"  {'Name':<28} {'Today: down/allowed':<22} New: down/allowed  (answers)")
    right = True
    for name in group:
        before, after = today[name], new[name]
        down_after = times - after["fine"]
        ok = down_after == times if want_down else down_after == 0
        right &= ok
        answers = ", ".join(f"{verdict} {n}" for verdict, n in after.most_common())
        mark = "  " if ok else "✗ "
        # Nothing for today's wording when it wasn't asked.
        was = f"{times - before['fine']} / {before['fine']}" if before else "-"
        print(f"{mark}{name:<28} {was:<22} {down_after} / {times - down_after}  ({answers})")
    return right


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--times", type=int, default=5, help="checks of each name")
    parser.add_argument("--asks", type=int, default=1, help="answers asked for at once")
    parser.add_argument("--office", type=Path, help="the office's display names, one a line")
    parser.add_argument("--new-only", action="store_true", help="skip today's wording")
    args = parser.parse_args()

    settings = get_settings()
    key = settings.openai_api_key.get_secret_value()
    ai = AIClient(key, settings.openai_model, settings.openai_effort)
    fine = FINE + (office_names(args.office) if args.office else [])
    every = list(dict.fromkeys(DESCRIBED + fine + STILL_NOT))
    calls = len(every) * args.times * args.asks * (1 if args.new_only else 2)
    effort = settings.openai_effort or "no"
    print(f"{settings.openai_model} ({effort} effort): {len(every)} names, {calls} calls")

    started = time.monotonic()
    new = await measure(ai, names.INSTRUCTIONS, names.VERDICT, every, args.times, args.asks)
    if args.new_only:
        today = {name: Counter() for name in every}
    else:
        today = await measure(ai, TODAY, TODAY_VERDICT, every, args.times, 1)
    await ai.close()

    described = show("Must be turned down", DESCRIBED, today, new, args.times, want_down=True)
    allowed = show("Must stay fine", fine, today, new, args.times, want_down=False)
    show("Still turned down: not names, or rude", STILL_NOT, today, new, args.times, True)
    print(f"\nTook {time.monotonic() - started:.0f} s, asking {args.asks} at a time.")
    print("Ships." if described and allowed else "Doesn't ship yet.")


if __name__ == "__main__":
    asyncio.run(main())
