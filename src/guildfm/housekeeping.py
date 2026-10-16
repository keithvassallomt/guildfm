"""Daily chores, since GuildFM runs for weeks without a restart: clearing out speech clips nobody
has used for a while, and making a backup. Both happen at startup too, the backup only if the
last one is over a day old."""

import asyncio
import logging
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from guildfm.backups import back_up, backups, made_at
from guildfm.speech import SpeechClient

log = logging.getLogger(__name__)

DAY = 24 * 60 * 60
CHECK_SECONDS = 60 * 60


class Housekeeping:
    def __init__(
        self,
        speech: SpeechClient,
        data_dir: Path,
        backup_dir: Path,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._speech = speech
        self._data_dir = data_dir
        self.backup_dir = backup_dir
        self.clock = clock
        self._pruned_at = float("-inf")

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("Housekeeping failed")
            await asyncio.sleep(CHECK_SECONDS)

    async def tick(self) -> None:
        now = self.clock()
        if now - self._pruned_at >= DAY:
            try:
                await asyncio.to_thread(self._speech.prune)
            except OSError:
                log.exception("Clearing out old speech clips failed")
            self._pruned_at = now
        made = backups(self.backup_dir)
        if made and now - made_at(made[-1]).timestamp() < DAY:
            return
        try:
            path = await asyncio.to_thread(
                back_up, self._data_dir, self.backup_dir, datetime.fromtimestamp(now)
            )
        except (OSError, sqlite3.Error) as error:
            log.error("Couldn't make the daily backup: %s", error)
            return
        log.info("Backed up to %s", path)
