"""Evening out how loud GuildFM's own audio is, so voices and jingles sit at about the music's
level. Text to speech comes out around -22 LUFS, well under most music.

It uses ffmpeg's loudnorm filter in two passes: one to measure, one to apply a steady gain with
a limit on the peaks. ffmpeg is optional: without it, audio plays at the level it came at.
"""

import asyncio
import json
import logging
import re
import shutil

log = logging.getLogger(__name__)

FFMPEG = shutil.which("ffmpeg")
PEAK = -1.5  # dBTP: room for the MP3 encoding without clipping
RANGE = 11  # LU: loudnorm's loudness range target


async def _ffmpeg(data: bytes, *args: str) -> tuple[bytes, str]:
    process = await asyncio.create_subprocess_exec(
        FFMPEG,
        "-hide_banner",
        "-nostats",
        "-i",
        "pipe:0",
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await process.communicate(data)
    if process.returncode != 0:
        raise RuntimeError(err.decode(errors="replace")[-300:])
    return out, err.decode(errors="replace")


async def level(data: bytes, loudness: float | None) -> bytes:
    """The MP3 in `data` at `loudness` LUFS, as a stereo MP3. Unchanged for None, without
    ffmpeg, or if ffmpeg can't make sense of it.

    Stereo because text to speech comes out mono, and the office speakers often stopped dead
    at the end of a mono clip in their queue instead of going on to the Spotify song after it.
    """
    if loudness is None or not FFMPEG:
        return data
    target = f"I={loudness}:TP={PEAK}:LRA={RANGE}"
    try:
        measure = f"loudnorm={target}:print_format=json"
        _, report = await _ffmpeg(data, "-af", measure, "-f", "null", "-")
        found = json.loads(re.findall(r"\{[^{}]*\}", report)[-1])
        measured = (
            f"measured_I={found['input_i']}:measured_TP={found['input_tp']}"
            f":measured_LRA={found['input_lra']}:measured_thresh={found['input_thresh']}"
            f":offset={found['target_offset']}"
        )
        out, _ = await _ffmpeg(
            data,
            "-af",
            f"loudnorm={target}:{measured}:linear=true",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            "-f",
            "mp3",
            "pipe:1",
        )
    except (OSError, RuntimeError, ValueError, KeyError, IndexError) as error:
        log.warning("Couldn't even out an audio clip's loudness: %s", error)
        return data
    return out or data
