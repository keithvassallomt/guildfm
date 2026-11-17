"""Rehearse a talk show with the real thing: GuildFM's own planning, writing and voicing (talk.py,
script.py, mixing.py), against OpenAI and ElevenLabs, with no speakers. Plans a show, then
writes and voices its first few segments, for listening to.

    uv run python -m tools.talk_rehearsal
    uv run python -m tools.talk_rehearsal --segments 4 --ratio 60 --seed 7 --play
    uv run python -m tools.talk_rehearsal --script-only

Host A is the first DJ in the local database, host B is Debbie (the account's voice of that
name), with the hooks and the dynamic from the prototype. Segments come in links as the station
makes them, with a song between links. Each run goes in its own folder in data/talk_rehearsal:
the plan; each segment's MP3, its script with what the edit fixed, and its draft before the
edit if it changed anything; and all of them together in show.mp3, where a short tone stands in
for each song. A segment costs about 1,000 ElevenLabs credits; --script-only writes the scripts
without voicing them, for a few cents of OpenAI.
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
from pathlib import Path
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


TONE_SECONDS = 1.5


def listed(turns: list[Turn]) -> str:
    return "\n".join(
        f"{t.speaker}{' (together)' if t.together else ''}: {t.text}"
        + (f'   <- cut after "{t.cut_after}"' if t.cut_after else "")
        for t in turns
    )


async def song_tone(folder: Path) -> Path | None:
    """A short, quiet tone standing in for a song in show.mp3, so it's clear where one plays."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    tone = folder / "speech" / "song.mp3"
    tone.parent.mkdir(exist_ok=True)
    filters = f"volume=0.2,afade=t=in:d=0.1,afade=t=out:st={TONE_SECONDS - 0.4}:d=0.4"
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=660:duration={TONE_SECONDS}",
        "-af",
        filters,
        "-ac",
        "2",
        "-ar",
        "44100",
        str(tone),
    )
    await process.wait()
    return tone if process.returncode == 0 else None


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
        link = lengths(args.ratio)
        wanted = min(args.segments, count)
        said: list[list[Turn]] = []
        notes, moves, clips, songs = "", [], [], []
        number = 0
        while number < wanted:
            move = deal_move(rng, hosts, False, moves, song=bool(songs))
            moves.append(move)
            before = SONGS[(len(songs) - 1) % len(SONGS)] if songs else None
            up_next = SONGS[len(songs) % len(SONGS)]
            for index, seconds in enumerate(link):
                if number >= wanted:
                    break
                number += 1
                ends_link = index == len(link) - 1 or number == wanted
                moment = Moment(
                    number=number,
                    count=count,
                    clock=clock_line(now),
                    first=number == 1,
                    ends_link=ends_link,
                    straight_on=index > 0,
                    before=before if index == 0 else None,
                    up_next=up_next if ends_link else None,
                    move=move if index == 0 else None,
                )
                started = time.monotonic()
                segment = await write_segment(
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
                turns, notes = segment.turns, segment.notes
                said.append(turns)
                script = listed(turns)
                fixes = "".join(f"\n- {fixed}" for fixed in segment.fixed)
                edit = f"\n\nEdited:{fixes}" if fixes else "\n\nEdited: nothing to fix."
                (folder / f"segment{number}.txt").write_text(script + f"\n\nNotes: {notes}{edit}\n")
                if segment.draft:
                    (folder / f"segment{number}-draft.txt").write_text(listed(segment.draft) + "\n")
                heading = f"\n=== Segment {number} ({move}): written in {written:.0f} s"
                if not args.script_only:
                    started = time.monotonic()
                    clip = await voice_segment(speech, turns, voices, rng)
                    voiced = time.monotonic() - started
                    clips.append((clip, ends_link))
                    shutil.copy(clip.path, folder / f"segment{number}.mp3")
                    heading += f", voiced in {voiced:.0f} s, {clip.seconds:.0f} s long"
                print(heading)
                print(script)
                print(f"Notes: {notes}{edit}")
                for mark in segment.marks:
                    print(f"  {mark}")
            songs.append(up_next)

        if args.script_only:
            print(f"\nSaved in {folder.relative_to(ROOT)}/")
            return
        tone = await song_tone(folder)
        at, parts = 0.0, []
        for clip, ends_link in clips:
            parts.append(Part(clip.path, at, 0.0, clip.seconds))
            at += clip.seconds + 0.5
            if ends_link and tone:
                parts.append(Part(tone, at, 0.0, TONE_SECONDS))
                at += TONE_SECONDS + 0.5
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

    if args.play and not args.script_only and shutil.which("mpv"):
        subprocess.run(["mpv", "--no-video", "--really-quiet", str(together)], check=False)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--segments", type=int, default=3, help="how many to write and voice")
    parser.add_argument("--ratio", type=int, default=40, help="percent talk (20 to 100)")
    parser.add_argument("--minutes", type=int, default=30, help="how long the show runs")
    parser.add_argument("--seed", type=int, help="for the same moves and dice every time")
    parser.add_argument("--play", action="store_true", help="play the show")
    parser.add_argument("--script-only", action="store_true", help="write, but don't voice")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(arguments()))
