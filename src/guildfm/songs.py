"""One song, whatever the version.

Spotify often has the same song under several ids: on the album, as a single, remastered, on a
compilation. George Michael's "Faith" is there three times. GuildFM knows a song by its main
artist and its title, without the version after a dash ("Faith - Remastered", "Rio - 2009
Remaster") or anything in brackets, so avoiding a song avoids every version of it.
"""

import re
from typing import Protocol

DASH = re.compile(r"\s+[-–]\s+")


class Titled(Protocol):
    """A track, from GuildFM's records or from Spotify."""

    title: str
    artists: str  # joined with commas, the main artist first


def plain(text: str) -> str:
    """Lower case, without "the", punctuation or brackets, for comparing names."""
    words = re.sub(r"[^\w\s]", " ", re.sub(r"\(.*?\)|\[.*?\]", " ", text.lower())).split()
    return " ".join(word for word in words if word != "the")


def bare_title(title: str) -> str:
    """The title without the version after a dash: "Faith - Remastered" is "Faith"."""
    return DASH.split(title, maxsplit=1)[0].strip() or title


def song_key(track: Titled) -> str:
    """The same for every version of a song."""
    artist = plain(track.artists.split(", ")[0])
    title = plain(bare_title(track.title)) or track.title.lower()
    return f"{artist}|{title}"


def song_line(track: Titled) -> str:
    """The song for the AI to read: its artists and title, without the version."""
    return f"{track.artists} – {bare_title(track.title)}"
