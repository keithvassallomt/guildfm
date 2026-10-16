"""Text to speech with OpenAI, saved as MP3s that the speakers fetch from GuildFM's /media.

The same words in the same voice are only ever asked for once: each MP3 is named after what
went into it, so a daily announcement, or a preview that's then scheduled, reuses the file.
"""

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx2

API = "https://api.openai.com/v1/audio/speech"
FOLDER = "speech"  # inside the media folder
KEPT_DAYS = 30  # MP3s nobody has used for this long are cleared out at startup
MAX_TEXT = 600  # characters; OpenAI's limit is far higher, but announcements are short


class SpeechError(Exception):
    """Text to speech didn't work. The message is fit to show people."""


@dataclass(frozen=True)
class Clip:
    path: Path
    seconds: float  # how long it plays

    @property
    def media_path(self) -> str:
        """Where it is under /media."""
        return f"{FOLDER}/{self.path.name}"


class SpeechClient:
    def __init__(
        self, api_key: str, model: str, media_dir: Path, http: httpx2.AsyncClient | None = None
    ) -> None:
        self._key = api_key
        self._model = model
        self._folder = media_dir / FOLDER
        self._http = http or httpx2.AsyncClient(timeout=30)

    async def close(self) -> None:
        await self._http.aclose()

    async def say(self, text: str, voice: str, instructions: str) -> Clip:
        """`text` read out in `voice`, delivered as `instructions` describe."""
        recipe = json.dumps([self._model, voice, instructions, text])
        path = self._folder / f"{hashlib.sha256(recipe.encode()).hexdigest()[:32]}.mp3"
        if path.exists():
            path.touch()  # still in use, so pruning leaves it
            return Clip(path, mp3_seconds(path.read_bytes()))

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

        data = response.content
        self._folder.mkdir(parents=True, exist_ok=True)
        draft = path.with_suffix(".tmp")
        draft.write_bytes(data)
        draft.replace(path)
        return Clip(path, mp3_seconds(data))

    def prune(self) -> None:
        """Clear out MP3s that haven't been used for a while."""
        if not self._folder.exists():
            return
        cutoff = time.time() - KEPT_DAYS * 24 * 60 * 60
        for path in self._folder.glob("*.mp3"):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)


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
