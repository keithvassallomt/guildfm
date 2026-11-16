"""Spike: two DJs in one link, talking over each other. The text model writes a short exchange
between two hosts, marking where one cuts the other off and where both speak at once. Each turn
is voiced on its own, several at a time, with ElevenLabs' timing for every character, and ffmpeg
mixes them: an interrupted turn is cut just after the words marked, with a quick fade, and the
next turn starts a fraction of a second before the cut.

    uv run python -m tools.dialogue_spike --list-voices
    uv run python -m tools.dialogue_spike --play
    uv run python -m tools.dialogue_spike --script data/dialogue_spike/<run>/turns.json --play

Each run goes in its own folder in data/dialogue_spike:
- overlap.mp3: the turns mixed, with the cuts and the overlaps
- plain.mp3: the same clips one after another, nothing cut, so free to make
- dialogue.mp3, with --dialogue: the same script through Text to Dialogue in one request
- turns.json: the script with its marks (edit it and voice it again with --script), script.txt
  to read, each turn's clip in turns/, and run.json with what it took

Host A is the first DJ in the local database. Host B is Debbie, voiced by the account's voice of
that name if it has one. Voicing costs ElevenLabs credits, about 0.44 a character on eleven_v4,
so a two-minute link is around 750; --dialogue doubles that.
"""

import argparse
import asyncio
import base64
import json
import random
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
from guildfm.audio import FFMPEG, level
from guildfm.awareness import clock_line
from guildfm.config import ROOT, Settings, get_settings
from guildfm.speech import ELEVEN, ELEVENLABS, mp3_seconds, without_tags

OUT = ROOT / "data" / "dialogue_spike"
LIMIT = 2000  # characters of text in one Text to Dialogue request
PER_SECOND = 17  # characters of speech in a second, as measured on eleven_v4
FORMAT = {"output_format": "mp3_44100_128"}
STATION = "GuildFM"
AT_ONCE = 4  # turns voiced at the same time; ElevenLabs limits how many a plan asks for at once
CONTEXT = 300  # characters of the turn before, given to ElevenLabs to pitch the reply
MAX_CUTS = 2  # interruptions in a link
GAP = (0.12, 0.45)  # seconds of quiet between turns, picked at random in this range
LEAD = 0.03  # seconds of quiet kept before a clip's first word
CUT_PAST = 0.06  # seconds of the next word heard before a cut
FADE = 0.05  # seconds a cut fades over
OVERLAP = 0.2  # seconds the interrupting turn starts before the cut
TOGETHER = 0.08  # at most this many seconds between two DJs speaking at once

A_PERSONALITY = "Funny, but not corny. Cheeky, a bit sarcastic, all in good fun."
B_NAME = "Debbie"
B_PERSONALITY = (
    "Bubbly, warm and mischievous. A northern lunchtime host who talks fast, laughs easily and "
    "has an opinion on everything."
)
# Keith's example in talk.md, with the names left to fill in.
DYNAMIC = (
    "{a} finds {b} too energetic, and often tries to calm {b} down during their shows. {b} loves "
    "to challenge {a}'s opinions and often sparks lively debates, and can't let {a} finish a "
    "story. The two have a history going back decades, and their chemistry is a big draw for "
    "listeners."
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
- They tease each other freely, and go gently on the people who request songs.
- Never make up facts about a song, an artist or a listener; leave out anything you weren't told.

They cut each other off, once or twice in the link, when it suits who they are. For a turn that \
gets cut off, write the whole sentence as the speaker meant to say it, and set cut_after to the \
last two or three words heard before the other host cuts in, copied exactly from that turn and \
well before its end. Start the next turn with [interrupting]. For every other turn, cut_after \
is empty.

Now and then both say something short at the same moment, such as both saying "No!": mark the \
second of the two turns together. For every other turn, together is false.

It's read out by an expressive text to speech model. An audio tag in square brackets before the \
words it's for steers the delivery, such as [laughs], [sighs], [sarcastic], [excited], \
[whispers] or [interrupting]. Use four at most in the whole link, besides [interrupting]. No \
other stage directions, sound effects or emoji. End by bringing in the next song."""


@dataclass(frozen=True)
class Host:
    name: str
    voice: str  # an ElevenLabs voice id
    personality: str


@dataclass(frozen=True)
class Turn:
    speaker: str  # a host's name
    text: str
    cut_after: str = ""  # cut off just after these words, which are in the text
    together: bool = False  # said at the same moment as the turn before


@dataclass(frozen=True)
class Clip:
    """A turn voiced, with when each character in it is said."""

    data: bytes
    seconds: float
    characters: list[str]
    starts: list[float]
    ends: list[float]
    credits: str | None  # what ElevenLabs says it cost

    def _said(self) -> list[int]:
        """The characters actually said: not spaces, and not audio tags."""
        inside, said = False, []
        for index, character in enumerate(self.characters):
            if character == "[":
                inside = True
            elif character == "]":
                inside = False
            elif not inside and character.strip():
                said.append(index)
        return said

    @property
    def speech(self) -> tuple[float, float]:
        """When the first word starts and the last one ends."""
        said = self._said()
        if not said:
            return 0.0, self.seconds
        return self.starts[said[0]], self.ends[said[-1]]

    def after(self, words: str) -> float | None:
        """When `words` have just been said, or None if they aren't in the timings."""
        text, owner = "", []
        for index, character in enumerate(self.characters):
            text += character
            owner += [index] * len(character)
        found = text.lower().find(words.lower())
        if found < 0:
            return None
        return self.ends[owner[found + len(words) - 1]]


@dataclass(frozen=True)
class Placed:
    """Where a clip goes in the mix."""

    turn: int  # its index in the turns
    at: float  # seconds into the mix where its kept part starts
    start: float  # seconds into the clip where the kept part starts
    end: float  # and where it ends
    cut: bool  # cut off by the next turn


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


def short_name(voice: dict[str, Any]) -> str:
    """ "Oliver" for "Oliver - Clean, British and Steady"."""
    return voice.get("name", "").split(" - ")[0].strip().lower()


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
        # The voice named for B first, then one easy to tell from A's, then British for a UK
        # office, then the account's own over premade.
        others.sort(
            key=lambda v: (
                short_name(v) != args.b_name.lower(),
                gender(v) is None or gender(v) == a_gender,
                not british(v),
                v.get("category") == "premade",
                v.get("name", ""),
            )
        )
        b_voice = others[0]["voice_id"]
        print(
            f"{args.b_name} is voiced by {described(others[0])}\n    Pick another with --b-voice."
        )
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
        speaker={"type": "string", "enum": [a.name, b.name]},
        text={"type": "string"},
        cut_after={"type": "string"},
        together={"type": "boolean"},
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
    turns = [
        Turn(t["speaker"], t["text"].strip(), t["cut_after"].strip(), t["together"])
        for t in answer["turns"]
    ]
    return turns, report


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
        return "the same host speaks next"
    if cuts >= MAX_CUTS:
        return f"there are already {MAX_CUTS} cuts"
    return None


def checked(turns: list[Turn]) -> tuple[list[Turn], list[str]]:
    """The turns with any mark that can't work taken off, and notes on what was taken off. A cut
    needs its words in the turn, well before its end, someone else speaking next, and no more
    than MAX_CUTS in the link. A turn said together needs another host's turn before it, not one
    that's cut off. The turn after a cut starts with an audio tag, [interrupting] if it has none."""
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


def read_script(path: Path, names: list[str]) -> list[Turn]:
    """Turns from a turns.json, or from a text file with a line each, "Name: what they say"."""
    if path.suffix == ".json":
        turns = [Turn(**turn) for turn in json.loads(path.read_text())]
        if stray := {t.speaker for t in turns} - set(names):
            raise SystemExit(f"{path}: {', '.join(stray)} isn't one of the hosts")
        return turns
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


def readable(turns: list[Turn]) -> str:
    lines = []
    for turn in turns:
        who = f"{turn.speaker} (at the same time)" if turn.together else turn.speaker
        cut = f'   <- cut off after "{turn.cut_after}"' if turn.cut_after else ""
        lines.append(f"{who}: {turn.text}{cut}")
    return "\n".join(lines)


async def post(
    http: httpx2.AsyncClient, key: str, path: str, body: dict[str, Any]
) -> httpx2.Response:
    response = await http.post(
        f"{ELEVENLABS}{path}", params=FORMAT, json=body, headers={"xi-api-key": key}
    )
    if response.status_code >= 400:
        raise SystemExit(f"ElevenLabs said {response.status_code} to {path}: {response.text[:500]}")
    return response


async def voice(
    http: httpx2.AsyncClient,
    key: str,
    model: str,
    turn: Turn,
    voice_id: str,
    before: str,
    gate: asyncio.Semaphore,
) -> Clip:
    """A turn voiced on its own, told what was said just before so it sounds like a reply."""
    body: dict[str, Any] = {"text": turn.text, "model_id": model}
    if before:
        body["previous_text"] = without_tags(before)[-CONTEXT:]
    async with gate:
        response = await post(http, key, f"/v1/text-to-speech/{voice_id}/with-timestamps", body)
    answer = response.json()
    timing = answer.get("alignment") or answer.get("normalized_alignment") or {}
    data = base64.b64decode(answer["audio_base64"])
    return Clip(
        data,
        mp3_seconds(data),
        timing.get("characters", []),
        timing.get("character_start_times_seconds", []),
        timing.get("character_end_times_seconds", []),
        response.headers.get("character-cost"),
    )


def placed(
    turns: list[Turn], clips: list[Clip], rng: random.Random, overlap: bool
) -> tuple[list[Placed], list[str]]:
    """Where each clip goes in the mix. One after another with a short, varied gap; with
    `overlap`, a turn marked cut ends just after its words with the next starting a little
    before, and a turn said together starts with the one before."""
    out: list[Placed] = []
    notes = []
    words_end = 0.0  # when the last words so far end, in the mix
    last_start = 0.0  # when the turn before started speaking, in the mix
    cut_at: float | None = None  # where the turn before was cut off, in the mix
    for index, (turn, clip) in enumerate(zip(turns, clips, strict=True)):
        said_from, said_to = clip.speech
        start, end, cut = max(0.0, said_from - LEAD), clip.seconds, False
        if overlap and turn.cut_after:
            when = clip.after(turn.cut_after)
            if when is not None and when + CUT_PAST < said_to - 0.2:
                end, cut = when + CUT_PAST, True
            else:
                words = turn.cut_after
                notes.append(f"Turn {index + 1} isn't cut: \"{words}\" isn't in the timings.")
        if index == 0:
            speak = said_from - start
        elif overlap and turn.together:
            speak = last_start + rng.uniform(0, TOGETHER)
        elif overlap and cut_at is not None:
            speak = cut_at - OVERLAP
        else:
            speak = words_end + rng.uniform(*GAP)
        at = speak - (said_from - start)
        out.append(Placed(index, round(at, 3), round(start, 3), round(end, 3), cut))
        last_start = speak
        cut_at = at + (end - start) if cut else None
        words_end = max(words_end, at + ((end if cut else said_to) - start))
    return out, notes


async def mix(clips: Path, placements: list[Placed], out: Path) -> None:
    """The clips in `clips` (01.mp3 for the first turn) mixed as placed, into `out`."""
    if not FFMPEG:
        raise SystemExit("Mixing needs ffmpeg.")
    args = [FFMPEG, "-hide_banner", "-nostats", "-y"]
    chains = []
    for number, place in enumerate(placements):
        args += ["-i", str(clips / f"{place.turn + 1:02d}.mp3")]
        chain = f"[{number}:a]atrim=start={place.start}:end={place.end},asetpts=PTS-STARTPTS"
        if place.cut:
            chain += f",afade=t=out:st={place.end - place.start - FADE:.3f}:d={FADE}"
        chains.append(f"{chain},adelay={round(place.at * 1000)}:all=1[c{number}]")
    inputs = "".join(f"[c{number}]" for number in range(len(placements)))
    graph = ";".join(
        [*chains, f"{inputs}amix=inputs={len(placements)}:normalize=0:dropout_transition=0[out]"]
    )
    args += ["-filter_complex", graph, "-map", "[out]", "-ac", "2", "-ar", "44100"]
    args += ["-b:a", "128k", str(out)]
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, err = await process.communicate()
    if process.returncode != 0:
        raise SystemExit(f"ffmpeg couldn't mix the turns: {err.decode(errors='replace')[-500:]}")


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


async def dialogue(
    http: httpx2.AsyncClient, key: str, model: str, turns: list[Turn], voices: dict[str, str]
) -> tuple[bytes, list[dict[str, Any]]]:
    """The turns voiced by Text to Dialogue, a request per run that fits, each told about the
    ones before so the voices stay the same. Nothing overlaps."""
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
                "credits": response.headers.get("character-cost"),
            }
        )
        if request_id := response.headers.get("request-id"):
            previous.append(request_id)
        audio += response.content
    return audio, report


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


def credits(values: list[str | None]) -> int | None:
    """What ElevenLabs said the requests cost, if it said for every one."""
    if not values or not all(v and v.isdigit() for v in values):
        return None
    return sum(int(v) for v in values if v)


async def main(args: argparse.Namespace) -> None:
    settings = get_settings()
    key = settings.elevenlabs_api_key.get_secret_value()
    if not key:
        raise SystemExit("Add ELEVENLABS_API_KEY to .env first.")
    model = args.model or settings.elevenlabs_model
    http = httpx2.AsyncClient(timeout=300)
    try:
        if args.list_voices:
            for found in await account_voices(http, key):
                print(described(found))
            return

        a, b = await hosts(args, http, key)
        voices = {a.name: a.voice, b.name: b.voice}
        run: dict[str, Any] = {"hosts": [asdict(a), asdict(b)], "voice_model": model}
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
        turns, notes = checked(turns)
        print(f"\n{readable(turns)}\n")

        folder = OUT / datetime.now().strftime("%Y%m%d-%H%M%S")
        (folder / "turns").mkdir(parents=True)
        (folder / "script.txt").write_text(readable(turns) + "\n")
        turns_json = json.dumps([asdict(t) for t in turns], indent=2, ensure_ascii=False)
        (folder / "turns.json").write_text(turns_json + "\n")

        gate = asyncio.Semaphore(AT_ONCE)
        started = time.monotonic()
        befores = ["", *(t.text for t in turns[:-1])]
        clips = await asyncio.gather(
            *(
                voice(http, key, model, turn, voices[turn.speaker], before, gate)
                for turn, before in zip(turns, befores, strict=True)
            )
        )
        run["seconds_to_voice"] = round(time.monotonic() - started, 1)
        for index, clip in enumerate(clips):
            (folder / "turns" / f"{index + 1:02d}.mp3").write_bytes(clip.data)

        rng = random.Random(args.seed)
        for name, overlap in (("overlap", True), ("plain", False)):
            placements, found = placed(turns, clips, rng, overlap)
            notes += found
            path = folder / f"{name}.mp3"
            await mix(folder / "turns", placements, path)
            path.write_bytes(await level(path.read_bytes(), settings.audio_loudness))
            run[name] = {
                "seconds": round(mp3_seconds(path.read_bytes()), 1),
                "placed": [asdict(p) for p in placements],
            }

        characters = sum(len(t.text) for t in turns)
        cost = credits([c.credits for c in clips])
        run.update(characters=characters, credits=cost, notes=notes)
        print(
            f"Voiced {len(turns)} turns, {AT_ONCE} at a time, in {run['seconds_to_voice']} s: "
            f"{characters} characters, {cost if cost is not None else 'unknown'} credits"
        )
        print(
            f"Overlapping: {minutes(run['overlap']['seconds'])}. "
            f"One after another: {minutes(run['plain']['seconds'])}."
        )
        if args.dialogue:
            audio, run["dialogue"] = await dialogue(http, key, model, turns, voices)
            (folder / "dialogue.mp3").write_bytes(await level(audio, settings.audio_loudness))
            spent = credits([r["credits"] for r in run["dialogue"]])
            voicing = sum(r["seconds_to_voice"] for r in run["dialogue"])
            print(f"Through Text to Dialogue: {voicing:.1f} s, {spent} credits")
        for note in notes:
            print(note)
        print(f"Saved in {folder.relative_to(ROOT)}/")
        (folder / "run.json").write_text(json.dumps(run, indent=2) + "\n")
    finally:
        await http.aclose()

    if args.play:
        print("\nPlaying them overlapping...")
        play(folder / "overlap.mp3")
        print("Now one after another...")
        play(folder / "plain.mp3")


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
    parser.add_argument("--script", help="voice this turns.json or script instead of writing one")
    parser.add_argument("--model", help="ElevenLabs model (default: .env's)")
    parser.add_argument("--seed", type=int, help="for the same gaps between turns every time")
    parser.add_argument(
        "--dialogue", action="store_true", help="also voice it through Text to Dialogue"
    )
    parser.add_argument("--play", action="store_true", help="play the results")
    args = parser.parse_args()
    if args.effort is None:
        args.effort = get_settings().openai_effort
    return args


if __name__ == "__main__":
    asyncio.run(main(arguments()))
