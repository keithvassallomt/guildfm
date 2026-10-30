"""Checking the names people pick for themselves, which the whole office sees beside their
requests: nothing vulgar, and a name or nickname rather than any old word. OpenAI judges. If it
can't be reached, or takes too long, the name goes through rather than stop people signing up."""

import asyncio
import logging
from enum import StrEnum

from guildfm.ai import AIClient, AIError, object_schema

log = logging.getLogger(__name__)

JUDGE_SECONDS = 10  # someone is waiting on the sign-up form


class Verdict(StrEnum):
    FINE = "fine"
    VULGAR = "vulgar"
    NOT_A_NAME = "not_a_name"


VERDICT = object_schema(verdict={"type": "string", "enum": [verdict.value for verdict in Verdict]})

INSTRUCTIONS = """\
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


async def judge(ai: AIClient, name: str) -> Verdict:
    """What OpenAI makes of `name`. FINE when it can't say."""
    try:
        async with asyncio.timeout(JUDGE_SECONDS):
            answer = await ai.json(INSTRUCTIONS, name, "name_check", VERDICT)
        return Verdict(answer["verdict"])
    except (AIError, TimeoutError, KeyError, ValueError) as error:
        log.warning("Couldn't check the name %r, so it went through: %s", name, error)
        return Verdict.FINE


async def name_problem(ai: AIClient, display_name: str, username: str | None = None) -> str | None:
    """Why the names someone picked won't do, fit to show them, or None when they're fine. A
    username only has to be clean: it's for signing in, so it needn't read like a name."""
    checks = [judge(ai, display_name)] + ([judge(ai, username)] if username else [])
    shown, *login = await asyncio.gather(*checks)
    if shown == Verdict.VULGAR:
        return "Pick a name you'd be happy for the whole office to see."
    if shown == Verdict.NOT_A_NAME:
        return "That doesn't look like a name. Use your own, or what people in the office call you."
    if login and login[0] == Verdict.VULGAR:
        return "Pick a username you'd be happy for the whole office to see."
    return None
