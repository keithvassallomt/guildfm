import asyncio
import json
import re
import subprocess

import pytest

from guildfm.audio import FFMPEG, level
from tests.fakes import mp3

pytestmark = pytest.mark.skipif(not FFMPEG, reason="ffmpeg isn't installed")


def loudness(data: bytes) -> float:
    """Integrated loudness in LUFS, as ffmpeg measures it."""
    report = subprocess.run(
        [FFMPEG, "-hide_banner", "-nostats", "-i", "pipe:0", "-af",
         "loudnorm=print_format=json", "-f", "null", "-"],
        input=data, capture_output=True, check=True,
    ).stderr.decode()  # fmt: skip
    return float(json.loads(re.findall(r"\{[^{}]*\}", report)[-1])["input_i"])


def quiet_tone() -> bytes:
    """Three seconds of a tone, well under music's loudness, like text to speech."""
    return subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=3", "-af", "volume=-24dB", "-f", "mp3", "pipe:1"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip


def test_quiet_audio_is_brought_up_to_the_target() -> None:
    before = quiet_tone()
    assert loudness(before) < -25
    after = asyncio.run(level(before, -14))
    assert loudness(after) == pytest.approx(-14, abs=1)


def test_mono_audio_comes_out_in_stereo() -> None:
    def layout(data: bytes) -> str:
        report = subprocess.run(
            [FFMPEG, "-hide_banner", "-i", "pipe:0"], input=data, capture_output=True
        ).stderr.decode()
        return re.search(r"Audio: mp3.*?Hz, (\w+)", report).group(1)

    before = quiet_tone()
    assert layout(before) == "mono"
    assert layout(asyncio.run(level(before, -14))) == "stereo"


def test_audio_that_cant_be_measured_is_left_alone() -> None:
    silence = mp3(1.0)
    assert asyncio.run(level(silence, -14)) == silence
    assert asyncio.run(level(b"not audio", -14)) == b"not audio"


def test_no_target_leaves_it_alone() -> None:
    tone = quiet_tone()
    assert asyncio.run(level(tone, None)) == tone
