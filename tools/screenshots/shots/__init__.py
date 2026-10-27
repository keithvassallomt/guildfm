"""Every screenshot in the help, by name, a module for each part of it. A topic shows one with
`![What it shows](shot:name)`.

A shot sets the page up and says what to frame. Shots look, they never change the office: no
saving. Anything a shot needs changed is a phase of the office (see office.PHASES)."""

from tools.screenshots.shots import (  # noqa: F401  (each registers its shots)
    announcements,
    lineups,
    listening,
    music,
    playlists,
    radio,
    running,
    start,
)
