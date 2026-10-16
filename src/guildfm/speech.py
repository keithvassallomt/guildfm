"""Text to speech, saved as MP3s that the speakers fetch from GuildFM's /media.

Voices are OpenAI's, named plainly ("marin"), or the ElevenLabs account's own, named
"elevenlabs:" and the voice's id. ElevenLabs voices understand audio tags in square brackets,
such as [laughs], to steer the delivery; OpenAI would read those out, so they're taken out
for OpenAI's voices.

The same words in the same voice are only ever asked for once: each MP3 is named after what
went into it, so a daily announcement, or a preview that's then scheduled, reuses the file.
"""

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
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
ELEVENLABS = "https://api.elevenlabs.io"
ELEVEN = "elevenlabs:"  # how an ElevenLabs voice's name starts
FOLDER = "speech"  # inside the media folder
KEPT_DAYS = 30  # MP3s nobody has used for this long are cleared out (see housekeeping.py)
MAX_TEXT = 600  # characters; OpenAI's limit is far higher, but announcements are short
VOICES_KEPT = 5 * 60  # seconds the ElevenLabs account's voices are remembered for
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
        loudness: float | None = None,
    ) -> None:
        self._key = api_key
        self._model = model
        self._eleven_key = eleven_key
        self._eleven_model = eleven_model
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
