"""Rehearse a talk show with the real thing: GuildFM's own planning, writing and voicing (talk.py,
script.py, mixing.py), against OpenAI and ElevenLabs, with no speakers. Plans a show, then
writes and voices its first few segments, for listening to.

    uv run python -m tools.talk_rehearsal
    uv run python -m tools.talk_rehearsal --segments 4 --ratio 60 --seed 7 --play

Host A is the first DJ in the local database, host B is Debbie (the account's voice of that
name), with the hooks and the dynamic from the prototype. Each run goes in its own folder in
data/talk_rehearsal: the plan, each segment's MP3 and script, and all of them together. A
segment costs about 1,000 ElevenLabs credits.
"""

import argparse
import asyncio
import json
import random
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx2

from guildfm.ai import AIClient
from guildfm.audio import Part, mix
from guildfm.awareness import Awareness, clock_line
from guildfm.config import ROOT, get_settings
from guildfm.fields import FROM_THE_WEB, used
from guildfm.mixing import voice_segment
from guildfm.script import Moment, Turn, write_segment
from guildfm.speech import ELEVEN, ELEVENLABS, SpeechClient, mp3_seconds
from guildfm.talk import (
    Host,
    deal_bits,
    deal_move,
    plan_show,
    roll_happening,
    segment_count,
)
from guildfm.talkshow import lengths

OUT = ROOT / "data" / "talk_rehearsal"
PROMPT = (
    "A lunchtime show of light chat between the two of them, with plenty of back and forth. A "
    "topic can run for one link, a few, or the whole show.\n\nDraw on the day's odd and funny "
    "news [news]. The weather [weather], and what it's doing to everyone's lunch plans. Last "
    "night's football [sports], and who's having a bad week."
)
DYNAMIC = (
    "Guildbert finds Debbie to be too energetic, and often tries to calm her down during their "
    "shows. Debbie, on the other hand, loves to challenge Guildbert's opinions and often sparks "
    "lively debates. She can't let him finish a story. The two have a history going back "
    "decades, and their chemistry is a big draw for listeners."
)
DEBBIE = Host(
    "Debbie",
    "Bubbly, warm and mischievous. A northern lunchtime host who talks fast, laughs easily and "
    "has an opinion on everything.",
    pet_peeves="People who say \"it's only Monday\". Guildbert's long stories.",
    soft_spots="ABBA. Anything you can dance to in a chair.",
)
SONGS = [
    '"Mr. Brightside" by The Killers',
    '"Dancing Queen" by ABBA',
    '"Valerie" by Amy Winehouse',
    '"September" by Earth, Wind & Fire',
    '"Don\'t Stop Me Now" by Queen',
]


def guildbert() -> tuple[Host, str]:
    with sqlite3.connect(ROOT / "data" / "guildfm.db") as db:
        name, voice, personality = db.execute(
            "SELECT name, voice, personality FROM djs ORDER BY id LIMIT 1"
        ).fetchone()
    db.close()
    host = Host(
        name,
        personality,
        pet_peeves="Songs that fade out instead of ending. Being called Gilbert.",
        soft_spots="Brass bands. Any song with a key change near the end.",
        obsession="His allotment's marrows, and the man two plots down who measures them.",
    )
    return host, voice


async def debbie_voice(key: str) -> str:
    async with httpx2.AsyncClient(timeout=30) as http:
        response = await http.get(
            f"{ELEVENLABS}/v2/voices",
            params={"page_size": 100},
            headers={"xi-api-key": key},
        )
    voices = response.json().get("voices", [])
    found = next(v for v in voices if v["name"].split(" - ")[0].strip() == "Debbie")
    return ELEVEN + found["voice_id"]


async def main(args: argparse.Namespace) -> None:
    settings = get_settings()
    key = settings.elevenlabs_api_key.get_secret_value()
    rng = random.Random(args.seed)
    folder = OUT / datetime.now().strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True)
    ai = AIClient(
        settings.openai_api_key.get_secret_value(),
        settings.openai_model,
        settings.openai_effort,
        httpx2.AsyncClient(timeout=300),
    )
    speech = SpeechClient(
        settings.openai_api_key.get_secret_value(),
        settings.openai_tts_model,
        folder,
        eleven_key=key,
        eleven_model=settings.elevenlabs_model,
        loudness=settings.audio_loudness,
    )
    awareness = Awareness(ai)
    try:
        a, a_voice = guildbert()
        hosts = [a, DEBBIE]
        voices = {a.name: a_voice, DEBBIE.name: await debbie_voice(key)}
        now = datetime.now(ZoneInfo("Europe/London"))
        credits_before = await speech.eleven_credits()

        print("Looking up the news, the weather and the football...")
        started = time.monotonic()
        web = [name for name in used(PROMPT) if name in FROM_THE_WEB]
        await awareness.ready(web, now.date(), 120)
        material = {name: awareness.gathered(name, now.date()) for name in web}
        weather = await awareness.weather("Carlisle, Cumbria, UK")
        if weather:
            material["weather"] = f"Right now in Carlisle, Cumbria, UK: {weather}."
        material = {name: text for name, text in material.items() if text}
        print(f"  {time.monotonic() - started:.0f} s")

        bits = deal_bits(rng, [])
        happening = roll_happening(rng, guests=False)
        started = time.monotonic()
        plan = await plan_show(
            ai,
            station="The Lunch Break",
            hosts=hosts,
            dynamic=DYNAMIC,
            prompt=PROMPT,
            material=material,
            starts=now,
            minutes=args.minutes,
            ratio=args.ratio,
            bits=bits,
            happening=happening,
            log=[],
        )
        print(f"Planned in {time.monotonic() - started:.0f} s: {json.dumps(plan, indent=2)}")
        (folder / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")

        count = segment_count(args.minutes, args.ratio)
        seconds = lengths(args.ratio)[0]
        said: list[list[Turn]] = []
        notes, moves, clips = "", [], []
        for number in range(1, min(args.segments, count) + 1):
            move = deal_move(rng, hosts, False, moves)
            moves.append(move)
            moment = Moment(
                number=number,
                count=count,
                clock=clock_line(now),
                first=number == 1,
                ends_link=True,
                before=SONGS[(number - 1) % len(SONGS)],
                up_next=SONGS[number % len(SONGS)],
                move=move,
            )
            started = time.monotonic()
            turns, notes, problems = await write_segment(
                ai,
                station="The Lunch Break",
                hosts=hosts,
                dynamic=DYNAMIC,
                prompt=PROMPT,
                plan=plan,
                moment=moment,
                material=material,
                notes=notes,
                said=said,
                seconds=seconds,
            )
            written = time.monotonic() - started
            started = time.monotonic()
            clip = await voice_segment(speech, turns, voices, rng)
            voiced = time.monotonic() - started
            said.append(turns)
            clips.append(clip)
            script = "\n".join(
                f"{t.speaker}{' (together)' if t.together else ''}: {t.text}"
                + (f'   <- cut after "{t.cut_after}"' if t.cut_after else "")
                for t in turns
            )
            shutil.copy(clip.path, folder / f"segment{number}.mp3")
            (folder / f"segment{number}.txt").write_text(script + f"\n\nNotes: {notes}\n")
            print(
                f"\n=== Segment {number} ({move}): written in {written:.0f} s, voiced in "
                f"{voiced:.0f} s, {clip.seconds:.0f} s long"
            )
            print(script)
            print(f"Notes: {notes}")
            for problem in problems:
                print(f"  {problem}")

        at, parts = 0.0, []
        for clip in clips:
            parts.append(Part(clip.path, at, 0.0, clip.seconds))
            at += clip.seconds + 1.0
        together = folder / "show.mp3"
        together.write_bytes(await mix(parts))
        credits_after = await speech.eleven_credits()
        if credits_before and credits_after:
            print(f"\nElevenLabs credits used: {credits_after.used - credits_before.used}")
        length = mp3_seconds(together.read_bytes())
        print(f"Saved in {folder.relative_to(ROOT)}/ ({length:.0f} s together in show.mp3)")
    finally:
        await awareness.close()
        await speech.close()
        await ai.close()

    if args.play and shutil.which("mpv"):
        subprocess.run(["mpv", "--no-video", "--really-quiet", str(together)], check=False)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--segments", type=int, default=3, help="how many to write and voice")
    parser.add_argument("--ratio", type=int, default=40, help="percent talk (20 to 100)")
    parser.add_argument("--minutes", type=int, default=30, help="how long the show runs")
    parser.add_argument("--seed", type=int, help="for the same moves and dice every time")
    parser.add_argument("--play", action="store_true", help="play the show")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(arguments()))
