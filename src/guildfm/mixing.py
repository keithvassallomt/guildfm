"""Voicing a talk station's segment so its DJs really talk over each other. Each turn is voiced
on its own, several at a time, with ElevenLabs' timing for every character, and the turns are
mixed into one clip: one after another with short, varied gaps; a turn marked cut ends just
after its words, with a quick fade, as the next comes in a fraction of a second before; and a
turn said together starts with the one before. The timings and gaps are the ones Keith heard
in the spike (tools/dialogue_spike.py) and liked."""

import asyncio
import random

from guildfm.audio import Part, mix
from guildfm.script import Turn
from guildfm.speech import Clip, SpeechClient, Timed

AT_ONCE = 4  # turns voiced at the same time; ElevenLabs limits how many a plan asks for at once
GAP = (0.12, 0.45)  # seconds of quiet between turns, picked at random in this range
LEAD = 0.03  # seconds of quiet kept before a clip's first word
CUT_PAST = 0.06  # seconds of the next word heard before a cut
OVERLAP = 0.2  # seconds the interrupting turn starts before the cut
TOGETHER = 0.08  # at most this many seconds between two DJs speaking at once


def _said(timed: Timed) -> list[int]:
    """The characters actually said: not spaces, and not audio tags."""
    inside, said = False, []
    for index, character in enumerate(timed.characters):
        if character == "[":
            inside = True
        elif character == "]":
            inside = False
        elif not inside and character.strip():
            said.append(index)
    return said


def speech(timed: Timed) -> tuple[float, float]:
    """When a turn's first word starts and its last one ends."""
    said = _said(timed)
    if not said:
        return 0.0, timed.clip.seconds
    return timed.starts[said[0]], timed.ends[said[-1]]


def after(timed: Timed, words: str) -> float | None:
    """When `words` have just been said in a turn, or None if they aren't in its timings."""
    text, owner = "", []
    for index, character in enumerate(timed.characters):
        text += character
        owner += [index] * len(character)
    found = text.lower().find(words.lower())
    if found < 0:
        return None
    return timed.ends[owner[found + len(words) - 1]]


def placed(turns: list[Turn], timed: list[Timed], rng: random.Random) -> list[Part]:
    """Where each turn's clip goes in the mix."""
    parts: list[Part] = []
    words_end = 0.0  # when the last words so far end, in the mix
    last_start = 0.0  # when the turn before started speaking, in the mix
    cut_at: float | None = None  # where the turn before was cut off, in the mix
    for index, (turn, voiced) in enumerate(zip(turns, timed, strict=True)):
        said_from, said_to = speech(voiced)
        start, end, cut = max(0.0, said_from - LEAD), voiced.clip.seconds, False
        if turn.cut_after:
            when = after(voiced, turn.cut_after)
            if when is not None and when + CUT_PAST < said_to - 0.2:
                end, cut = when + CUT_PAST, True
        if index == 0:
            speak = said_from - start
        elif turn.together:
            speak = last_start + rng.uniform(0, TOGETHER)
        elif cut_at is not None:
            speak = cut_at - OVERLAP
        else:
            speak = words_end + rng.uniform(*GAP)
        at = max(0.0, speak - (said_from - start))
        parts.append(Part(voiced.clip.path, round(at, 3), round(start, 3), round(end, 3), cut))
        last_start = speak
        cut_at = at + (end - start) if cut else None
        words_end = max(words_end, at + ((end if cut else said_to) - start))
    return parts


async def voice_segment(
    speech_client: SpeechClient,
    turns: list[Turn],
    voices: dict[str, str],
    rng: random.Random | None = None,
) -> Clip:
    """A segment's turns voiced and mixed into one clip. `voices` has each DJ's ElevenLabs
    voice, by name."""
    gate = asyncio.Semaphore(AT_ONCE)

    async def one(turn: Turn, before: str) -> Timed:
        async with gate:
            return await speech_client.say_timed(turn.text, voices[turn.speaker], before)

    befores = ["", *(turn.text for turn in turns[:-1])]
    timed = await asyncio.gather(*(one(t, b) for t, b in zip(turns, befores, strict=True)))
    parts = placed(turns, list(timed), rng or random.Random())
    return await speech_client.keep(await mix(parts))
