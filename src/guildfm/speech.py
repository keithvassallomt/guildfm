"""Text to speech, saved as MP3s that the speakers fetch from GuildFM's /media.

Voices are OpenAI's, named plainly ("marin"), or the ElevenLabs account's own, named
"elevenlabs:" and the voice's id. ElevenLabs voices understand audio tags in square brackets,
such as [laughs], to steer the delivery; OpenAI would read those out, so they're taken out
for OpenAI's voices.

The same words in the same voice are only ever asked for once: each MP3 is named after what
went into it, so a daily announcement, or a preview that's then scheduled, reuses the file.
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Annotated

import httpx2
from pydantic import AfterValidator
from pydantic_core import PydanticCustomError

from guildfm.audio import FFMPEG, level
from guildfm.health import Health
from guildfm.prefs import VOICES

log = logging.getLogger(__name__)

API = "https://api.openai.com/v1/audio/speech"
HEARING = "https://api.openai.com/v1/audio/transcriptions"
ELEVENLABS = "https://api.elevenlabs.io"
ELEVEN = "elevenlabs:"  # how an ElevenLabs voice's name starts
FOLDER = "speech"  # inside the media folder
KEPT_DAYS = 30  # MP3s nobody has used for this long are cleared out (see housekeeping.py)
MAX_TEXT = 600  # characters; OpenAI's limit is far higher, but announcements are short
VOICES_KEPT = 5 * 60  # seconds the ElevenLabs account's voices are remembered for
MUSIC_SECONDS = 240  # making music can take a couple of minutes
# Seconds to wait before asking again when ElevenLabs says it's busy making other music.
MUSIC_WAITS = (5, 15, 30)
SHORTEST_PART = 3000  # ms: the shortest part of a piece of music ElevenLabs will plan
NO_VOICE = ["vocals", "singing", "spoken word"]  # styles kept out of an instrumental
_VOCAL = re.compile(
    r"\b(vocals?|voices?|sing\w*|sung|choir|chant\w*|rap|rapped|harmon\w*|spoken)\b",
    re.IGNORECASE,
)
_QUOTED = re.compile(r'["\u201c]([^"\u201d]+)["\u201d]')  # words in "quotes", or curly ones
CREDITS_KEPT = 60  # seconds the ElevenLabs account's credits are remembered for

_ELEVEN_VOICE = re.compile(rf"{ELEVEN}[A-Za-z0-9]{{1,40}}")
# Words in square brackets, such as [laughs] or [sighs, quietly], but not [3].
_TAG = re.compile(r"\s*\[[A-Za-z][A-Za-z ,'-]{0,39}\]")


def is_eleven(voice: str) -> bool:
    return voice.startswith(ELEVEN)


def _voice(value: str) -> str:
    if value in VOICES or _ELEVEN_VOICE.fullmatch(value):
        return value
    raise PydanticCustomError("voice", "That isn't one of GuildFM's voices.")


# An OpenAI voice's name, or an ElevenLabs voice's.
Voice = Annotated[str, AfterValidator(_voice)]


def without_tags(text: str) -> str:
    """`text` without audio tags such as [laughs], for a voice that would read them out."""
    return _TAG.sub("", text).strip()


class SpeechError(Exception):
    """Text to speech didn't work. The message is fit to show people."""


class PromptRefused(SpeechError):
    """ElevenLabs won't make music from that description, such as one naming a real band. It
    may suggest its own wording instead."""

    def __init__(self, message: str, suggestion: str | None = None) -> None:
        super().__init__(message)
        self.suggestion = suggestion


@dataclass(frozen=True)
class Clip:
    path: Path
    seconds: float  # how long it plays
    folder: str = FOLDER  # the folder it's in, inside the media folder

    @property
    def media_path(self) -> str:
        """Where it is under /media."""
        return f"{self.folder}/{self.path.name}"


@dataclass(frozen=True)
class Music:
    data: bytes  # an MP3, as ElevenLabs made it
    words: str  # what it was asked to sing, a line each; empty for none


@dataclass(frozen=True)
class ElevenVoice:
    voice: str  # "elevenlabs:" and its id
    name: str


@dataclass(frozen=True)
class Credits:
    """The ElevenLabs account's credits this month."""

    used: int
    limit: int
    resets_at: float | None  # seconds since the epoch


class SpeechClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        media_dir: Path,
        http: httpx2.AsyncClient | None = None,
        *,
        eleven_key: str = "",
        eleven_model: str = "eleven_v4",
        eleven_music_model: str = "music_v2_5",
        hearing_model: str = "gpt-4o-transcribe",
        loudness: float | None = None,
    ) -> None:
        self._key = api_key
        self._model = model
        self._hearing_model = hearing_model
        self._eleven_key = eleven_key
        self._eleven_model = eleven_model
        self._music_model = eleven_music_model
        # Clips are evened out to this, in LUFS, when ffmpeg is about; else left as they come.
        self._loudness = loudness if FFMPEG else None
        if loudness is not None and not FFMPEG:
            log.warning("ffmpeg isn't installed, so voices play quieter than the music")
        self._folder = media_dir / FOLDER
        self._http = http or httpx2.AsyncClient(timeout=30)
        self._voices: list[ElevenVoice] = []
        self._voices_at = float("-inf")  # when they were read, by time.monotonic
        self._credits: Credits | None = None
        self._credits_at = float("-inf")
        self.openai_health = Health()
        self.eleven_health = Health()
        self.sleep = asyncio.sleep  # tests wait for nothing

    @property
    def eleven_ready(self) -> bool:
        """Whether there's an ElevenLabs key to use."""
        return bool(self._eleven_key)

    async def close(self) -> None:
        await self._http.aclose()

    async def say(self, text: str, voice: str, instructions: str) -> Clip:
        """`text` read out in `voice`. OpenAI's voices deliver it as `instructions` describe;
        ElevenLabs voices go by their own settings and any audio tags in the text."""
        if is_eleven(voice):
            recipe = [self._eleven_model, voice, text]
        else:
            text = without_tags(text)
            recipe = [self._model, voice, instructions, text]
        if self._loudness is not None:
            recipe.append(f"{self._loudness} LUFS")
        name = hashlib.sha256(json.dumps(recipe).encode()).hexdigest()[:32]
        path = self._folder / f"{name}.mp3"
        if path.exists():
            path.touch()  # still in use, so pruning leaves it
            return Clip(path, mp3_seconds(path.read_bytes()))

        health = self.eleven_health if is_eleven(voice) else self.openai_health
        try:
            if is_eleven(voice):
                data = await self._eleven(text, voice.removeprefix(ELEVEN))
            else:
                data = await self._openai(text, voice, instructions)
        except SpeechError as error:
            health.failed(str(error))
            raise
        health.worked()
        data = await level(data, self._loudness)
        self._folder.mkdir(parents=True, exist_ok=True)
        draft = path.with_suffix(".tmp")
        draft.write_bytes(data)
        draft.replace(path)
        return Clip(path, mp3_seconds(data))

    async def _openai(self, text: str, voice: str, instructions: str) -> bytes:
        body = {
            "model": self._model,
            "voice": voice,
            "input": text,
            "instructions": instructions,
            "response_format": "mp3",
        }
        try:
            response = await self._http.post(
                API, json=body, headers={"Authorization": f"Bearer {self._key}"}
            )
        except httpx2.HTTPError as error:
            raise SpeechError("Couldn't reach OpenAI. Check the internet connection.") from error
        if response.status_code == 401:
            raise SpeechError("OpenAI turned GuildFM's key down. Check OPENAI_API_KEY in .env.")
        if response.status_code == 429:
            raise SpeechError(
                "OpenAI is busy, or the account is out of credit. Try again in a minute."
            )
        if response.status_code >= 400:
            raise SpeechError("OpenAI couldn't read that out just now. Try again.")
        return response.content

    async def _eleven(self, text: str, voice_id: str) -> bytes:
        if not self._eleven_key:
            raise SpeechError("ElevenLabs isn't set up. Add ELEVENLABS_API_KEY to .env.")
        try:
            response = await self._http.post(
                f"{ELEVENLABS}/v1/text-to-speech/{voice_id}",
                params={"output_format": "mp3_44100_128"},
                json={"text": text, "model_id": self._eleven_model},
                headers={"xi-api-key": self._eleven_key},
            )
        except httpx2.HTTPError as error:
            raise SpeechError(
                "Couldn't reach ElevenLabs. Check the internet connection."
            ) from error
        if response.status_code >= 400:
            raise SpeechError(_eleven_problem(response))
        return response.content

    async def compose(self, prompt: str, seconds: int, instrumental: bool = False) -> Music:
        """Music made by ElevenLabs from `prompt`, `seconds` long. With `instrumental`, there's
        no voice at all. Raises PromptRefused for a description it won't make, and SpeechError
        for anything else.

        ElevenLabs plans the piece from the description first, which costs nothing, then makes
        it from the plan fitted to the length: made from a description alone, it can run several
        seconds over. The words in the plan are kept to the ones quoted in the description. When
        it's busy making other music, it's asked again a little later."""
        try:
            music = await self._music(prompt, seconds * 1000, instrumental)
        except SpeechError as error:
            self.eleven_health.failed(str(error))
            raise
        self.eleven_health.worked()
        return music

    async def heard(self, data: bytes) -> str:
        """The words OpenAI hears in an MP3: none, or a note like "\U0001f3b6", for music without
        them."""
        try:
            response = await self._http.post(
                HEARING,
                data={"model": self._hearing_model},
                files={"file": ("jingle.mp3", data, "audio/mpeg")},
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=60,
            )
            response.raise_for_status()
            text = response.json()["text"]
        except (httpx2.HTTPError, KeyError, TypeError, ValueError) as error:
            self.openai_health.failed("Couldn't listen for the words in a jingle.")
            raise SpeechError("OpenAI couldn't listen for the words just now.") from error
        self.openai_health.worked()
        return str(text)

    async def _music(self, prompt: str, length: int, instrumental: bool) -> Music:
        if not self._eleven_key:
            raise SpeechError("ElevenLabs isn't set up. Add ELEVENLABS_API_KEY to .env.")
        asked = f"{prompt} Instrumental only: no vocals." if instrumental else prompt
        plan = await self._eleven_music(
            "/v1/music/plan",
            {"prompt": asked, "music_length_ms": length, "model_id": self._music_model},
        )
        try:
            chunks = plan.json().get("chunks")
        except ValueError, AttributeError:
            chunks = None
        words = [] if instrumental else quoted(prompt)
        if chunks:
            parts = fit(chunks, length, instrumental, words)
            body = {"composition_plan": {"chunks": parts}, "model_id": self._music_model}
            words = [line for part in parts for line in part["text"].splitlines() if _sung(line)]
        else:  # a model that plans another way, such as music_v1: the description it is
            body = {
                "prompt": prompt,
                "music_length_ms": length,
                "model_id": self._music_model,
                "force_instrumental": instrumental,
            }
        made = await self._eleven_music("/v1/music", body, {"output_format": "mp3_44100_128"})
        return Music(made.content, "\n".join(words))

    async def _eleven_music(
        self, path: str, body: dict, params: dict | None = None
    ) -> httpx2.Response:
        """A call to ElevenLabs' music API, asked again a few times while it's busy."""
        for wait in (*MUSIC_WAITS, None):
            try:
                response = await self._http.post(
                    f"{ELEVENLABS}{path}",
                    params=params,
                    json=body,
                    headers={"xi-api-key": self._eleven_key},
                    timeout=MUSIC_SECONDS,
                )
            except httpx2.HTTPError as error:
                raise SpeechError(
                    "Couldn't reach ElevenLabs. Check the internet connection."
                ) from error
            if response.status_code == 429 and wait is not None:
                log.info("ElevenLabs is busy making music; asking again in %s seconds", wait)
                await self.sleep(wait)
                continue
            if response.status_code >= 400:
                log.warning("ElevenLabs couldn't make music: %s", response.text[:300])
                raise _music_problem(response)
            return response
        raise AssertionError("unreachable")

    async def eleven_voices(self) -> list[ElevenVoice]:
        """The voices made in the ElevenLabs account, by name. Remembered for a few minutes;
        none without a key, or while ElevenLabs can't be reached."""
        if not self._eleven_key:
            return []
        if time.monotonic() - self._voices_at < VOICES_KEPT:
            return self._voices
        try:
            response = await self._http.get(
                f"{ELEVENLABS}/v2/voices",
                params={"voice_type": "personal", "page_size": 100, "sort": "name"},
                headers={"xi-api-key": self._eleven_key},
            )
            response.raise_for_status()
            found = response.json().get("voices", [])
        except (httpx2.HTTPError, ValueError) as error:
            log.warning("Couldn't list the ElevenLabs voices: %s", error)
            self.eleven_health.failed("Couldn't list the ElevenLabs voices.")
            return self._voices
        self.eleven_health.worked()
        self._voices = sorted(
            (ElevenVoice(ELEVEN + v["voice_id"], v.get("name") or "Unnamed") for v in found),
            key=lambda voice: voice.name.lower(),
        )
        self._voices_at = time.monotonic()
        return self._voices

    async def eleven_credits(self) -> Credits | None:
        """The ElevenLabs account's credits this month, remembered for a minute. None without a
        key, or when ElevenLabs won't say, such as for a key without permission to read them."""
        if not self._eleven_key:
            return None
        if time.monotonic() - self._credits_at < CREDITS_KEPT:
            return self._credits
        try:
            response = await self._http.get(
                f"{ELEVENLABS}/v1/user/subscription", headers={"xi-api-key": self._eleven_key}
            )
            response.raise_for_status()
            found = response.json()
            self._credits = Credits(
                used=int(found["character_count"]),
                limit=int(found["character_limit"]),
                resets_at=found.get("next_character_count_reset_unix"),
            )
        except httpx2.HTTPError, KeyError, TypeError, ValueError:
            self._credits = None
        self._credits_at = time.monotonic()
        return self._credits

    def prune(self) -> None:
        """Clear out MP3s that haven't been used for a while."""
        if not self._folder.exists():
            return
        cutoff = time.time() - KEPT_DAYS * 24 * 60 * 60
        for path in self._folder.glob("*.mp3"):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)


def _eleven_problem(response: httpx2.Response) -> str:
    """What went wrong with ElevenLabs, fit to show people."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    status = detail.get("status") if isinstance(detail, dict) else None
    if status == "quota_exceeded":
        return "ElevenLabs is out of credits. Top up the account, or pick an OpenAI voice."
    if response.status_code == 401:
        return "ElevenLabs turned GuildFM's key down. Check ELEVENLABS_API_KEY in .env."
    if response.status_code == 404 or status == "voice_not_found":
        return "ElevenLabs can't find that voice any more. Pick another."
    if response.status_code == 429:
        return "ElevenLabs is busy. Try again in a minute."
    return "ElevenLabs couldn't read that out just now. Try again."


def quoted(text: str) -> list[str]:
    """The words in quotes in a description: the ones to be sung."""
    return [found.strip() for found in _QUOTED.findall(text) if found.strip()]


def sang(heard: str, words: str) -> bool:
    """Whether what OpenAI heard has any of the words that were to be sung, give or take a
    letter or two ("Gild FM" for "Guild F M")."""
    said = re.findall(r"[a-z0-9']+", heard.lower())
    lines = re.sub(r"\([^)]*\)", "", words.lower())  # not ad libs such as (ooh)
    wanted = [word for word in re.findall(r"[a-z0-9']+", lines) if len(word) >= 3]
    if not wanted:
        return bool(said)
    return any(SequenceMatcher(None, w, s).ratio() >= 0.75 for w in wanted for s in said)


def fit(
    chunks: list, length: int, instrumental: bool = False, words: list[str] | None = None
) -> list[dict]:
    """ElevenLabs' plan for a piece of music, made exactly `length` ms long. Its own plans can
    run over, and each part has to be at least 3 seconds, so a short piece gets fewer parts.

    For an instrumental, the words come out and voices are kept out. Otherwise its words are
    kept to `words`, the ones the description quotes, since its plans add lines of their own,
    and the voices go in the first part's styles too, which set the tone for the whole piece:
    without, the words sometimes go unsung."""
    parts = [_part(chunk, instrumental) for chunk in chunks if isinstance(chunk, dict)]
    if not parts:
        raise SpeechError("ElevenLabs couldn't plan that one. Try again.")
    if words:
        _keep_to(parts, words)
    if not instrumental and any(_has_words(part) for part in parts):
        voices = [s for part in parts for s in part["positive_styles"] if _VOCAL.search(s)]
        first = parts[0]["positive_styles"]
        first += [style for style in dict.fromkeys(voices or ["lead vocals"]) if style not in first]
    while len(parts) > max(1, length // SHORTEST_PART):
        last = parts.pop()
        parts[-1] = _joined(parts[-1], last)
    # Each part keeps 3 seconds, and what's left is shared out as ElevenLabs had it.
    over = [max(0, part["duration_ms"] - SHORTEST_PART) for part in parts]
    shares = over if sum(over) else [1] * len(parts)
    spare = length - SHORTEST_PART * len(parts)
    for part, share in zip(parts, shares, strict=True):
        part["duration_ms"] = SHORTEST_PART + spare * share // sum(shares)
    longest = max(parts, key=lambda part: part["duration_ms"])
    longest["duration_ms"] += length - sum(part["duration_ms"] for part in parts)
    return parts


def _part(chunk: dict, instrumental: bool) -> dict:
    """A part of ElevenLabs' plan, with only the fields a plan takes back."""
    text = str(chunk.get("text") or "")
    positive = [str(style) for style in chunk.get("positive_styles") or []]
    negative = [str(style) for style in chunk.get("negative_styles") or []]
    if instrumental:
        # Section names in [] and directions in {} stay; the lines between them are words.
        lines = text.splitlines()
        text = "\n".join(line for line in lines if line.strip().startswith(("[", "{")))
        positive = [style for style in positive if not _VOCAL.search(style)] + ["instrumental"]
        negative += [style for style in NO_VOICE if style not in negative]
    part = {
        "text": text or "[Instrumental]",
        "duration_ms": int(chunk.get("duration_ms") or SHORTEST_PART),
        "positive_styles": positive or ["radio jingle"],
        "negative_styles": negative,
    }
    if chunk.get("context_adherence") in ("low", "medium", "high"):
        part["context_adherence"] = chunk["context_adherence"]
    return part


def _sung(line: str) -> bool:
    """A line of words in a plan, rather than a [section] or a {direction}."""
    line = line.strip()
    return bool(line) and not line.startswith(("[", "{"))


def _has_words(part: dict) -> bool:
    return any(_sung(line) for line in part["text"].splitlines())


def _plain(text: str) -> str:
    """Lower case letters and digits, a space between words, to compare words by."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _keep_to(parts: list[dict], words: list[str]) -> None:
    """Take out the lines of words that aren't in `words`; ad libs in brackets stay. If that
    leaves none, `words` go where the first words were."""
    wanted = _plain(" ".join(words))
    had = [part for part in parts if _has_words(part)]
    for part in parts:
        part["text"] = "\n".join(
            line
            for line in part["text"].splitlines()
            if not _sung(line) or _plain(re.sub(r"\([^)]*\)", "", line)) in wanted
        )
    if any(_has_words(part) for part in parts):
        return
    into = had[0] if had else max(parts, key=lambda part: part["duration_ms"])
    lines = into["text"].splitlines()
    at = 1 if lines and lines[0].strip().startswith("[") else 0
    into["text"] = "\n".join(lines[:at] + words + lines[at:])


def _joined(first: dict, second: dict) -> dict:
    """Two parts of a plan as one."""
    return first | {
        "text": f"{first['text']}\n{second['text']}",
        "duration_ms": first["duration_ms"] + second["duration_ms"],
        "positive_styles": first["positive_styles"]
        + [style for style in second["positive_styles"] if style not in first["positive_styles"]],
        "negative_styles": first["negative_styles"]
        + [style for style in second["negative_styles"] if style not in first["negative_styles"]],
    }


def _music_problem(response: httpx2.Response) -> SpeechError:
    """What went wrong making music with ElevenLabs, fit to show people."""
    try:
        detail = response.json().get("detail")
    except ValueError, AttributeError:
        detail = None
    detail = detail if isinstance(detail, dict) else {}
    status = detail.get("status")
    if status in ("bad_prompt", "bad_composition_plan"):
        data = detail.get("data")
        suggestion = data.get("prompt_suggestion") if isinstance(data, dict) else None
        return PromptRefused(
            "ElevenLabs won't make music that names a real artist, band or song, or quotes real "
            "lyrics.",
            suggestion if isinstance(suggestion, str) and suggestion.strip() else None,
        )
    if status == "quota_exceeded":
        return SpeechError("ElevenLabs is out of credits. Top up the account, then try again.")
    if status == "missing_permissions":
        return SpeechError(
            "GuildFM's ElevenLabs key isn't allowed to make music. Give it access to Music in "
            "ElevenLabs."
        )
    if response.status_code == 401:
        return SpeechError(
            "ElevenLabs turned GuildFM's key down. Check ELEVENLABS_API_KEY in .env."
        )
    if response.status_code in (402, 403):
        return SpeechError("The ElevenLabs account's plan doesn't include music.")
    if response.status_code == 429:
        return SpeechError("ElevenLabs is busy making other music. Try again in a minute.")
    return SpeechError("ElevenLabs couldn't make that one just now. Try again.")


# MP3 frame headers, for working out how long a clip plays. Layer III only, which is what
# OpenAI and nearly every encoder make.
_BITRATES = {  # kbps, by bitrate index
    "mpeg1": (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    "mpeg2": (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
_SAMPLE_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def mp3_seconds(data: bytes) -> float:
    """How long an MP3 plays, counted frame by frame."""
    index = 0
    if data[:3] == b"ID3" and len(data) >= 10:
        size = 0
        for byte in data[6:10]:
            size = size << 7 | byte & 0x7F
        index = 10 + size
    seconds = 0.0
    while index + 4 <= len(data):
        first, second, third = data[index], data[index + 1], data[index + 2]
        version = second >> 3 & 3  # 3 is MPEG-1, 2 MPEG-2, 0 MPEG-2.5
        layer = second >> 1 & 3  # 1 is Layer III
        bitrate_index, rate_index, padding = third >> 4, third >> 2 & 3, third >> 1 & 1
        if (
            first != 0xFF
            or second & 0xE0 != 0xE0
            or version == 1
            or layer != 1
            or bitrate_index in (0, 15)
            or rate_index == 3
        ):
            index += 1  # not a frame header; look further on
            continue
        mpeg1 = version == 3
        bitrate = _BITRATES["mpeg1" if mpeg1 else "mpeg2"][bitrate_index] * 1000
        rate = _SAMPLE_RATES[version][rate_index]
        samples = 1152 if mpeg1 else 576
        seconds += samples / rate
        index += samples // 8 * bitrate // rate + padding
    return seconds
