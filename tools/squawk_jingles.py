"""Jingles for The Squawk Box in its DJs' own voices. ElevenLabs' music model can't speak in a
DJ's voice and tends to leave spoken lines out, so each jingle is made in two parts: the lines
are voiced in Guildbert's and Debbie's ElevenLabs voices and laid out like a talk station's
turns (mixing.py), then the music is made from a plan sized around them: an instrumental intro,
an instrumental groove for as long as they talk, and a sung tag at the end. The music dips
under the voices.

    uv run python -m tools.squawk_jingles 1

Each run goes in its own folder in data/squawk_jingles: jingle.mp3 to listen to, with bed.mp3
(the music alone), voices.mp3 (the lines alone), plan.json (what the music model was asked for)
and run.json (lengths, what was heard in the tag, credits used).

The voices come from the local database's DJs. The music costs ElevenLabs music credits, and
is made again once if the tag's words can't be heard in it.
"""

import argparse
import asyncio
import json
import random
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx2

from guildfm.audio import FFMPEG, Part, level, mix
from guildfm.config import ROOT, get_settings
from guildfm.mixing import placed
from guildfm.script import Turn
from guildfm.speech import NO_VOICE, SpeechClient, mp3_seconds

OUT = ROOT / "data" / "squawk_jingles"
INTRO_MS = 3000  # the shortest part ElevenLabs will plan
TAG_MS = 3000
VOICES_AT = 1.8  # seconds in that the first line starts, over the end of the intro
AFTER_VOICES = 0.4  # seconds of groove after the last line before the tag
# Music made at most this many times, until the tag's words are heard. One: on jingle 1 the
# transcription heard German in a choir Keith heard sing the name fine.
TRIES = 1


@dataclass(frozen=True)
class Jingle:
    name: str
    styles: list[str]  # the whole piece
    intro: list[str]
    groove: list[str]  # under the voices
    tag: list[str]
    words: str  # sung in the tag
    lines: list[Turn] = field(default_factory=list)


JINGLES = {
    1: Jingle(
        name="The ident",
        styles=[
            "80s synth-pop",
            "118 BPM",
            "gated reverb snare",
            "big chorus synths",
            "bright and upbeat",
            "radio jingle",
        ],
        intro=["two-bar synth fanfare"],
        groove=["steady bass and drums groove", "sparse", "leaves room for talking"],
        tag=["choir vocals", "a choir sings the station name", "one final big chord"],
        words="The Squawk Box",
        lines=[
            Turn("Debbie", "You're listening to The Squawk Box! [laughs]"),
            Turn("Guildbert", "[deadpan] She's very proud of that."),
        ],
    ),
    2: Jingle(
        name="Yoghurt suspects",
        styles=[
            "90s TV detective theme",
            "95 BPM",
            "plucked strings",
            "creeping walking bass",
            "muted brass",
            "tense and sneaky",
            "radio jingle",
        ],
        intro=["one suspenseful chord", "a creeping bass line starts"],
        groove=["quiet sneaky groove", "sparse", "leaves room for talking"],
        tag=["sharp brass sting", "choir vocals", "a choir sings the station name"],
        words="The Squawk Box",
        lines=[
            Turn("Debbie", "Someone's had my yoghurt again."),
            Turn("Guildbert", "It wasn't me."),
            Turn("Debbie", "That's exactly what a suspect would say."),
        ],
    ),
    3: Jingle(
        name="Quiz night",
        styles=[
            "cheesy 80s TV quiz-show theme",
            "120 BPM",
            "synth brass",
            "ticking clock",
            "radio jingle",
        ],
        intro=["short quiz-show fanfare"],
        groove=["quiet ticking clock over a soft synth pad", "sparse", "leaves room for talking"],
        tag=[
            "game-show buzzer",
            "triumphant fanfare",
            "choir vocals",
            "a choir sings the station name",
        ],
        words="The Squawk Box",
        lines=[
            Turn(
                "Guildbert",
                "Question one. Where can you hear the best of the eighties, nineties and "
                "noughties?",
            ),
            Turn("Debbie", "The Squawk Box! Do I win?"),
            Turn("Guildbert", "You come second. We always come second."),
        ],
    ),
    4: Jingle(
        name="Same song twice",
        styles=[
            "00s pop-punk",
            "160 BPM",
            "crunchy distorted guitars",
            "fast drums",
            "energetic",
            "radio jingle",
        ],
        intro=["power-chord intro", "the band stops dead"],
        groove=["near silence", "one held guitar chord ringing out", "leaves room for talking"],
        tag=[
            "the band crashes back in",
            "gang vocals shouting the station name",
            "hard stop",
        ],
        words="The Squawk Box!",
        lines=[
            Turn("Debbie", "Same song, twice, before lunch?"),
            Turn("Guildbert", "Bold."),
            Turn("Debbie", "No."),
            Turn("Guildbert", "No.", together=True),
        ],
    ),
    5: Jingle(
        name="Kettle's on",
        styles=[
            "laid-back late-90s chill-out",
            "90 BPM",
            "dusty breakbeat",
            "warm electric piano",
            "vinyl crackle",
            "mellow",
            "radio jingle",
        ],
        intro=["electric piano chords", "the breakbeat fades in"],
        groove=["mellow loop", "sparse", "leaves room for talking"],
        # A soft close harmony left the name unsung, so a lead vocal sings it, and Debbie says
        # it too.
        tag=[
            "warm lead vocal",
            "sings the station name clearly",
            "soft backing harmonies",
            "ends on a warm chord",
        ],
        words="The Squawk Box",
        lines=[
            Turn("Debbie", "Kettle's on, biscuits are out, it's The Squawk Box."),
            Turn("Guildbert", "Last one's mine."),
            Turn("Debbie", "[laughing] Over my dead body."),
        ],
    ),
}


def voices(names: set[str]) -> dict[str, str]:
    with sqlite3.connect(f"file:{ROOT / 'data' / 'guildfm.db'}?mode=ro", uri=True) as db:
        rows = db.execute("select name, voice from djs").fetchall()
    found = {name: voice for name, voice in rows if name in names}
    missing = names - found.keys()
    if missing:
        raise SystemExit(f"No DJ called {', '.join(sorted(missing))} in the local database.")
    return found


def plan(jingle: Jingle, groove_ms: int) -> list[dict]:
    instrumental = ["instrumental"]
    return [
        {
            "text": "[Intro]",
            "duration_ms": INTRO_MS,
            "positive_styles": jingle.styles + jingle.intro + instrumental,
            "negative_styles": NO_VOICE,
        },
        {
            "text": "[Instrumental]",
            "duration_ms": groove_ms,
            "positive_styles": jingle.styles + jingle.groove + instrumental,
            "negative_styles": NO_VOICE,
        },
        {
            "text": f"[Outro]\n{jingle.words}",
            "duration_ms": TAG_MS,
            "positive_styles": jingle.styles + jingle.tag,
            "negative_styles": ["spoken word"],
        },
    ]


async def ducked(bed: Path, spoken: Path, seconds: float) -> bytes:
    """The voices over the music, with the music dipping while they talk."""
    process = await asyncio.create_subprocess_exec(
        FFMPEG,
        "-hide_banner",
        "-nostats",
        "-i",
        str(bed),
        "-i",
        str(spoken),
        "-filter_complex",
        f"[1:a]apad=whole_dur={seconds:.3f},asplit=2[key][talk];"
        "[0:a][key]sidechaincompress=threshold=0.02:ratio=10:attack=10:release=400[dipped];"
        "[dipped][talk]amix=inputs=2:normalize=0:duration=first[out]",
        "-map",
        "[out]",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "128k",
        "-f",
        "mp3",
        "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(err.decode(errors="replace")[-300:])
    return out


async def main(number: int) -> None:
    jingle = JINGLES[number]
    settings = get_settings()
    folder = OUT / f"{datetime.now():%Y%m%d-%H%M%S}-{number}"
    folder.mkdir(parents=True)
    speech = SpeechClient(
        settings.openai_api_key.get_secret_value(),
        settings.openai_tts_model,
        folder,
        httpx2.AsyncClient(timeout=300),
        eleven_key=settings.elevenlabs_api_key.get_secret_value(),
        eleven_model=settings.elevenlabs_model,
        eleven_music_model=settings.elevenlabs_music_model,
    )
    loudness = settings.audio_loudness
    try:
        before = await speech.eleven_credits()
        by_name = voices({turn.speaker for turn in jingle.lines})

        print("Voicing the lines...")
        said_before = ["", *(turn.text for turn in jingle.lines[:-1])]
        timed = [
            await speech.say_timed(turn.text, by_name[turn.speaker], b)
            for turn, b in zip(jingle.lines, said_before, strict=True)
        ]
        parts = [
            Part(p.path, round(p.at + VOICES_AT, 3), p.start, p.end, p.fade)
            for p in placed(jingle.lines, timed, random.Random(number))
        ]
        voices_end = max(p.at + p.end - p.start for p in parts)
        groove_ms = max(3000, round((voices_end + AFTER_VOICES) * 1000) - INTRO_MS)
        seconds = (INTRO_MS + groove_ms + TAG_MS) / 1000
        spoken = await level(await mix(parts), loudness)
        (folder / "voices.mp3").write_bytes(spoken)
        print(f"  lines end at {voices_end:.1f} s; the jingle will be {seconds:.1f} s")

        chunks = plan(jingle, groove_ms)
        (folder / "plan.json").write_text(json.dumps(chunks, indent=2))
        heard, bed = "", b""
        for attempt in range(1, TRIES + 1):
            print(f"Making the music (try {attempt})...")
            body = {
                "composition_plan": {"chunks": chunks},
                "model_id": settings.elevenlabs_music_model,
            }
            # A one-off tool, so it borrows SpeechClient's retrying music call.
            made = await speech._eleven_music("/v1/music", body, {"output_format": "mp3_44100_128"})
            bed = made.content
            heard = await speech.heard(bed)
            print(f"  heard: {heard!r}")
            if "squawk" in heard.lower():
                break
        bed = await level(bed, loudness)
        (folder / "bed.mp3").write_bytes(bed)

        out = await ducked(folder / "bed.mp3", folder / "voices.mp3", seconds)
        out = await level(out, loudness)
        (folder / "jingle.mp3").write_bytes(out)
        after = await speech.eleven_credits()
        run = {
            "jingle": number,
            "name": jingle.name,
            "seconds": round(mp3_seconds(out), 2),
            "voices_end": round(voices_end, 2),
            "tag_heard": heard,
            "tries": attempt,
            "credits_used": after.used - before.used if before and after else None,
        }
        (folder / "run.json").write_text(json.dumps(run, indent=2))
        print(json.dumps(run, indent=2))
        print(f"\nListen: {folder / 'jingle.mp3'}")
    finally:
        await speech.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("number", type=int, choices=sorted(JINGLES))
    asyncio.run(main(parser.parse_args().number))
