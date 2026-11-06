"""What's new: a short note for people after GuildFM updates, shown once to each of them the next
time they open GuildFM or come back to it, whether or not they sign in again.

A version with something to tell has a Markdown file in whats_new named for it, such as
0.1.3.md. Most versions have none. The text is read like a help topic, so a `::: needs x` block
is only for people who can x, and `[words](topic:id)` links to the help.
"""

from pathlib import Path

from guildfm import __version__

FOLDER = Path(__file__).parent / "whats_new"
LATEST = 3  # someone away for a while hears about the last few versions, not every one


def _order(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def unseen(seen: str, running: str | None = None, folder: Path | None = None) -> list[dict]:
    """The notes someone hasn't seen: for versions after `seen`, up to the one running, newest
    first. A note for a version not out yet waits until it is."""
    after, upto = _order(seen), _order(running or __version__)
    found = []
    for path in (folder or FOLDER).glob("*.md"):
        version = _order(path.stem)
        if after < version <= upto:
            found.append((version, {"version": path.stem, "text": path.read_text()}))
    found.sort(key=lambda each: each[0], reverse=True)
    return [note for _, note in found[:LATEST]]
