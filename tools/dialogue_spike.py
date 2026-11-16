"""Spike: two DJs in one link. The text model writes a short exchange between two hosts, and
ElevenLabs' Text to Dialogue voices it in one request, so their timing and reactions come out as
one conversation. With --compare, the same script is also voiced a turn at a time, the way
GuildFM voices its one DJ today, and joined end to end, so the two can be heard side by side.

    uv run python -m tools.dialogue_spike --list-voices
    uv run python -m tools.dialogue_spike --compare --play
    uv run python -m tools.dialogue_spike --script data/dialogue_spike/<run>/script.txt --play

Host A is the first DJ in the local database, host B is made up here, with a voice picked from
the ElevenLabs account to sound unlike A's. Each run goes in its own folder in
data/dialogue_spike: the MP3s, the script (edit it and voice it again with --script) and what
it took. Voicing costs ElevenLabs characters, about $0.08 per thousand, so a two-minute link is
about $0.15; --compare doubles that.
"""

import argparse
import asyncio
import json
import re
import shutil
import sqlite3
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx2

from guildfm.ai import AIClient, AIError, Usage, object_schema
from guildfm.audio import level
from guildfm.awareness import clock_line
from guildfm.config import ROOT, Settings, get_settings
from guildfm.speech import ELEVEN, ELEVENLABS, mp3_seconds

OUT = ROOT / "data" / "dialogue_spike"
LIMIT = 2000  # characters of text in one Text to Dialogue request
PER_SECOND = 14  # characters of speech in a second, roughly
PRICE = 0.08  # dollars per 1,000 characters for eleven_v4 on the API, November 2026
FORMAT = {"output_format": "mp3_44100_128"}
STATION = "GuildFM"

A_PERSONALITY = "Funny, but not corny. Cheeky, a bit sarcastic, all in good fun."
B_NAME = "Fern"
B_PERSONALITY = (
    "New to the station and far better prepared than anyone needs to be. Keeps a spreadsheet of "
    "every request, quotes chart positions, and takes music very seriously. Earnest and quick, "
    "easily wound up, and gives as good as they get once wound up."
)
DYNAMIC = (
    "{a} had the station alone for months and treats {b} as the new kid. {b} is better prepared "
    "and keeps correcting {a} with facts, which {a} can't stand. They like each other, and would "
    "never admit it."
)
BRIEF = (
    'A link in the middle of the lunchtime show. Just played: "Mr. Brightside" by The Killers, '
    'requested by Sam for the third time this week. Up next: "Dancing Queen" by ABBA, requested '
    "by Priya. Running bit: when the show opened, {a} bet {b} a biscuit that nobody would "
    "request ABBA today. Settle the bet, then bring in the song."
)
INSTRUCTIONS = """You write the talk on {station}, a radio station playing over the speakers in \
an office in the UK. Today's show has two hosts.

{a}: {a_personality}
{b}: {b_personality}
How they get on: {dynamic}

Write the next link, what the two of them say between two songs, as a list of turns: about \
{chars} characters of speech in all, around {seconds} seconds.

Make it sound like two people, not one person split in two:
- They have different opinions, and say so. They don't praise each other's points or finish \
each other's sentences.
- Each keeps to their own way of talking.
- Turns vary in length: a story, a two-word reply, a line that gets cut off.
- They use each other's names now and then, so listeners learn who's who.
- Someone can cut in: end the cut-off turn mid-sentence with an ellipsis, and start the next \
turn with [interrupting].
- They tease each other freely, and go gently on the people who request songs.
- Never make up facts about a song or an artist; leave trivia out unless you're sure of it.

It's read out by an expressive text to speech model. An audio tag in square brackets before the \
words it's for steers the delivery, such as [laughs], [sighs], [sarcastic], [excited], \
[whispers] or [interrupting]. Use four at most in the whole link. No other stage directions, \
sound effects or emoji. End by bringing in the next song."""


@dataclass(frozen=True)
class Host:
    name: str
    voice: str  # an ElevenLabs voice id
    personality: str


@dataclass(frozen=True)
class Turn:
    speaker: str  # a host's name
    text: str


def first_dj() -> tuple[str, str, str] | None:
    """The name, ElevenLabs voice id and personality of the first DJ in the local database."""
    path = ROOT / "data" / "guildfm.db"
    if not path.exists():
        return None
    with sqlite3.connect(path) as db:
        row = db.execute("select name, voice, personality from djs order by id limit 1").fetchone()
    if not row or not row[1].startswith(ELEVEN):
        return None
    return row[0], row[1].removeprefix(ELEVEN), row[2] or A_PERSONALITY


async def account_voices(http: httpx2.AsyncClient, key: str) -> list[dict[str, Any]]:
    response = await http.get(
        f"{ELEVENLABS}/v2/voices",
        params={"page_size": 100, "sort": "name"},
        headers={"xi-api-key": key},
    )
    if response.status_code >= 400:
        raise SystemExit(f"ElevenLabs wouldn't list the voices: {response.text[:300]}")
    return response.json().get("voices", [])


def labels(voice: dict[str, Any]) -> dict[str, str]:
    return voice.get("labels") or {}


def description(voice: dict[str, Any]) -> str:
    return " ".join((voice.get("description") or "").split())


def gender(voice: dict[str, Any]) -> str | None:
    """From the labels, or for a voice designed from a description, such as "A British woman in
    her late 50s", from that."""
    if found := labels(voice).get("gender"):
        return found
    words = re.findall(r"\b(female|woman|male|man)\b", description(voice).lower())
    if not words:
        return None
    return "female" if words[0] in ("female", "woman") else "male"


def british(voice: dict[str, Any]) -> bool:
    return labels(voice).get("accent") == "british" or "british" in description(voice).lower()


def described(voice: dict[str, Any]) -> str:
    about = ", ".join(v for k in ("gender", "age", "accent") if (v := labels(voice).get(k)))
    line = f"{voice['voice_id']}  {voice.get('name', '?')} ({voice.get('category', '?')}; {about})"
    return f"{line}\n    {description(voice)[:150]}" if description(voice) else line


async def hosts(args: argparse.Namespace, http: httpx2.AsyncClient, key: str) -> tuple[Host, Host]:
    dj = first_dj()
    a_name = args.a_name or (dj[0] if dj else None)
    a_voice = args.a_voice or (dj[1] if dj else None)
    if not a_name or not a_voice:
        raise SystemExit("No DJ with an ElevenLabs voice in the local database: give --a-voice.")
    a = Host(a_name, a_voice, dj[2] if dj and a_name == dj[0] else A_PERSONALITY)

    b_voice = args.b_voice
    if not b_voice:
        found = await account_voices(http, key)
        a_gender = next((gender(v) for v in found if v["voice_id"] == a.voice), None)
        others = [v for v in found if v["voice_id"] != a.voice]
        if not others:
            raise SystemExit("The account has no other voice for host B: give --b-voice.")
        # Easy to tell from A's first, then British for a UK office, then the account's own.
        others.sort(
            key=lambda v: (
                gender(v) is None or gender(v) == a_gender,
                not british(v),
                v.get("category") == "premade",
                v.get("name", ""),
            )
        )
        b_voice = others[0]["voice_id"]
        print(f"{args.b_name} is voiced by {described(others[0])}. Pick another with --b-voice.")
    return a, Host(args.b_name, b_voice, B_PERSONALITY)


async def write(
    settings: Settings, a: Host, b: Host, brief: str, seconds: int, effort: str
) -> tuple[list[Turn], dict[str, Any]]:
    instructions = INSTRUCTIONS.format(
        station=STATION,
        a=a.name,
        b=b.name,
        a_personality=a.personality,
        b_personality=b.personality,
        dynamic=DYNAMIC.format(a=a.name, b=b.name),
        chars=seconds * PER_SECOND,
        seconds=seconds,
    )
    prompt = f"{clock_line(datetime.now())}\n\n{brief.format(a=a.name, b=b.name)}"
    turn = object_schema(
        speaker={"type": "string", "enum": [a.name, b.name]}, text={"type": "string"}
    )
    schema = object_schema(turns={"type": "array", "items": turn})
    ai = AIClient(
        settings.openai_api_key.get_secret_value(),
        settings.openai_model,
        effort,
        httpx2.AsyncClient(timeout=300),
    )
    usage = Usage()
    started = time.monotonic()
    try:
        answer = await ai.json(instructions, prompt, "link", schema, usage)
    except AIError as error:
        raise SystemExit(f"Couldn't write the link: {error}") from error
    finally:
        await ai.close()
    report = {
        "model": settings.openai_model,
        "effort": effort,
        "seconds_to_write": round(time.monotonic() - started, 1),
        "tokens": asdict(usage),
        "instructions": instructions,
        "prompt": prompt,
    }
    return [Turn(t["speaker"], t["text"].strip()) for t in answer["turns"]], report


def read_script(path: Path, names: list[str]) -> list[Turn]:
    """Turns from a file with a line each, "Name: what they say"."""
    turns = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        speaker, colon, text = line.partition(":")
        if not colon or speaker.strip() not in names:
            who = " or ".join(names)
            raise SystemExit(f"{path}:{number}: start the line with {who} and a colon")
        turns.append(Turn(speaker.strip(), text.strip()))
    return turns


def chunks(turns: list[Turn]) -> list[list[Turn]]:
    """The turns in runs that each fit in one Text to Dialogue request."""
    runs: list[list[Turn]] = []
    size = 0
    for turn in turns:
        if len(turn.text) > LIMIT:
            raise SystemExit(f"One turn is over {LIMIT} characters: {turn.text[:60]}...")
        if runs and size + len(turn.text) <= LIMIT:
            runs[-1].append(turn)
            size += len(turn.text)
        else:
            runs.append([turn])
            size = len(turn.text)
    return runs


def billing(response: httpx2.Response) -> dict[str, str]:
    """Response headers that might say what a request cost, or identify it."""
    words = ("char", "cost", "request-id")
    return {k: v for k, v in response.headers.items() if any(w in k.lower() for w in words)}


async def post(
    http: httpx2.AsyncClient, key: str, path: str, body: dict[str, Any]
) -> httpx2.Response:
    response = await http.post(
        f"{ELEVENLABS}{path}", params=FORMAT, json=body, headers={"xi-api-key": key}
    )
    if response.status_code >= 400:
        raise SystemExit(f"ElevenLabs said {response.status_code} to {path}: {response.text[:500]}")
    return response


async def dialogue(
    http: httpx2.AsyncClient, key: str, model: str, turns: list[Turn], voices: dict[str, str]
) -> tuple[bytes, list[dict[str, Any]]]:
    """The turns voiced by Text to Dialogue, a request per run that fits, each told about the
    ones before so the voices stay the same."""
    audio = b""
    report = []
    previous: list[str] = []
    for run in chunks(turns):
        body: dict[str, Any] = {
            "inputs": [{"text": t.text, "voice_id": voices[t.speaker]} for t in run],
            "model_id": model,
        }
        if previous:
            body["previous_request_ids"] = previous[-3:]
        started = time.monotonic()
        response = await post(http, key, "/v1/text-to-dialogue", body)
        report.append(
            {
                "turns": len(run),
                "characters": sum(len(t.text) for t in run),
                "seconds_to_voice": round(time.monotonic() - started, 1),
                "headers": billing(response),
            }
        )
        if request_id := response.headers.get("request-id"):
            previous.append(request_id)
        audio += response.content
    return audio, report


async def stitched(
    http: httpx2.AsyncClient, key: str, model: str, turns: list[Turn], voices: dict[str, str]
) -> tuple[bytes, float]:
    """The turns voiced one at a time by plain text to speech and joined end to end."""
    started = time.monotonic()
    audio = b""
    for turn in turns:
        body = {"text": turn.text, "model_id": model}
        audio += (await post(http, key, f"/v1/text-to-speech/{voices[turn.speaker]}", body)).content
    return audio, round(time.monotonic() - started, 1)


def play(path: Path) -> None:
    if shutil.which("mpv"):
        subprocess.run(["mpv", "--no-video", "--really-quiet", str(path)], check=False)
    elif shutil.which("ffplay"):
        subprocess.run(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)], check=False
        )
    else:
        print(f"No mpv or ffplay to play {path}")


def minutes(seconds: float) -> str:
    return f"{int(seconds // 60)} min {round(seconds % 60)} s"


async def main(args: argparse.Namespace) -> None:
    settings = get_settings()
    key = settings.elevenlabs_api_key.get_secret_value()
    if not key:
        raise SystemExit("Add ELEVENLABS_API_KEY to .env first.")
    model = args.model or settings.elevenlabs_model
    http = httpx2.AsyncClient(timeout=300)
    try:
        if args.list_voices:
            for voice in await account_voices(http, key):
                print(described(voice))
            return

        a, b = await hosts(args, http, key)
        voices = {a.name: a.voice, b.name: b.voice}
        run: dict[str, Any] = {
            "hosts": [asdict(a), asdict(b)],
            "voice_model": model,
            "price_per_1000": PRICE,
        }
        if args.script:
            turns = read_script(Path(args.script), [a.name, b.name])
        else:
            print(f"Writing a {args.seconds} s link for {a.name} and {b.name}...")
            turns, run["writing"] = await write(
                settings, a, b, args.brief or BRIEF, args.seconds, args.effort
            )
            took = run["writing"]
            print(
                f"Written in {took['seconds_to_write']} s "
                f"({took['tokens']['input']} tokens in, {took['tokens']['output']} out)"
            )
        script = "\n".join(f"{t.speaker}: {t.text}" for t in turns)
        print(f"\n{script}\n")

        folder = OUT / datetime.now().strftime("%Y%m%d-%H%M%S")
        folder.mkdir(parents=True)
        (folder / "script.txt").write_text(script + "\n")

        characters = sum(len(t.text) for t in turns)
        audio, run["dialogue"] = await dialogue(http, key, model, turns, voices)
        audio = await level(audio, settings.audio_loudness)
        (folder / "dialogue.mp3").write_bytes(audio)
        voicing = sum(r["seconds_to_voice"] for r in run["dialogue"])
        length = mp3_seconds(audio)
        print(
            f"Voiced {characters} characters in {len(run['dialogue'])} request(s): "
            f"{voicing:.1f} s to make, {minutes(length)} of audio "
            f"({characters / length:.1f} characters a second)"
        )
        cost = characters / 1000 * PRICE
        if args.compare:
            joined, run["stitched_seconds_to_voice"] = await stitched(
                http, key, model, turns, voices
            )
            (folder / "stitched.mp3").write_bytes(await level(joined, settings.audio_loudness))
            print(f"Voiced a turn at a time in {run['stitched_seconds_to_voice']} s")
            cost *= 2
        for request in run["dialogue"]:
            if request["headers"]:
                print(f"ElevenLabs' headers: {request['headers']}")
        print(f"About ${cost:.2f}. Saved in {folder.relative_to(ROOT)}/")

        run.update(characters=characters, audio_seconds=round(length, 1), dollars=round(cost, 3))
        (folder / "run.json").write_text(json.dumps(run, indent=2) + "\n")
    finally:
        await http.aclose()

    if args.play:
        print("\nPlaying the dialogue...")
        play(folder / "dialogue.mp3")
        if args.compare:
            print("Now the same script, a turn at a time...")
            play(folder / "stitched.mp3")


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--list-voices", action="store_true", help="list the account's voices")
    parser.add_argument("--a-name", help="host A's name (default: the first DJ)")
    parser.add_argument("--a-voice", help="host A's ElevenLabs voice id")
    parser.add_argument("--b-name", default=B_NAME, help=f"host B's name (default: {B_NAME})")
    parser.add_argument("--b-voice", help="host B's ElevenLabs voice id (default: picked)")
    parser.add_argument("--brief", help="what the link is about; {a} and {b} are the hosts")
    parser.add_argument("--seconds", type=int, default=120, help="how long a link to write")
    parser.add_argument("--effort", help="how hard the text model thinks (default: .env's)")
    parser.add_argument("--script", help="voice this script instead of writing one")
    parser.add_argument("--model", help="ElevenLabs model (default: .env's)")
    parser.add_argument("--compare", action="store_true", help="also voice it a turn at a time")
    parser.add_argument("--play", action="store_true", help="play the result")
    args = parser.parse_args()
    if args.effort is None:
        args.effort = get_settings().openai_effort
    return args


if __name__ == "__main__":
    asyncio.run(main(arguments()))
