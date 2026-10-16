"""Logging. GuildFM's own lines go to the console, which is the journal when it runs as a service,
and the latest warnings and errors are kept for the admins' status page."""

import logging
import os
import sys
from collections import deque
from dataclasses import dataclass

KEPT = 50
LONGEST = 300  # characters of a message kept
# GuildFM's own lines, and uvicorn's, which has the errors from handling requests.
WATCHED = ("guildfm", "uvicorn.error")


@dataclass
class Problem:
    at: float  # when it last happened, in seconds since the epoch
    level: str  # "warning" or "error"
    source: str  # where it came from, such as "guildfm.radio"
    message: str
    count: int = 1  # how many times it's happened


class Recent(logging.Handler):
    """Keeps the latest warnings and errors, newest first. One that happens again moves back to
    the top and counts up, so a recurring problem doesn't push the others out."""

    def __init__(self, kept: int = KEPT) -> None:
        super().__init__(logging.WARNING)
        self.problems: deque[Problem] = deque(maxlen=kept)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            error = record.exc_info[1] if record.exc_info else None
            if error is not None:
                message = f"{message}: {type(error).__name__}: {error}"
            message = message[:LONGEST]
        except Exception:
            self.handleError(record)
            return
        for problem in self.problems:
            if (problem.source, problem.message) == (record.name, message):
                self.problems.remove(problem)
                problem.at, problem.count = record.created, problem.count + 1
                self.problems.appendleft(problem)
                return
        level = "error" if record.levelno >= logging.ERROR else "warning"
        self.problems.appendleft(Problem(record.created, level, record.name, message))

    def attach(self) -> None:
        for name in WATCHED:
            logging.getLogger(name).addHandler(self)

    def detach(self) -> None:
        for name in WATCHED:
            logging.getLogger(name).removeHandler(self)


class _Console(logging.StreamHandler):
    """Writes to whatever stderr is at the time, since tests swap it about."""

    @property
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, _) -> None:
        pass


def to_console() -> None:
    """Send GuildFM's own lines, from INFO up, to the console. Once, however many apps are made.
    Under systemd the journal adds the time itself."""
    logger = logging.getLogger("guildfm")
    if any(isinstance(handler, _Console) for handler in logger.handlers):
        return
    handler = _Console()
    stamp = "" if os.environ.get("JOURNAL_STREAM") else "%(asctime)s "
    handler.setFormatter(
        logging.Formatter(f"{stamp}%(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
