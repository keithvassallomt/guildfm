"""How GuildFM's outside services have been doing, for the admins' status page: when each last
worked, and when and why it last failed. Nothing is checked specially; each client notes how its
own calls went."""

import time
from dataclasses import dataclass
from typing import Literal

State = Literal["ok", "failing", "unused"]


@dataclass
class Health:
    ok_at: float | None = None  # seconds since the epoch
    failed_at: float | None = None
    problem: str | None = None  # why it last failed, fit to show people

    def worked(self) -> None:
        self.ok_at = time.time()

    def failed(self, problem: str) -> None:
        self.failed_at, self.problem = time.time(), problem

    @property
    def state(self) -> State:
        """By how its latest call went, or "unused" before the first."""
        if self.ok_at is None and self.failed_at is None:
            return "unused"
        return "failing" if (self.failed_at or 0) > (self.ok_at or 0) else "ok"

    @staticmethod
    def together(*records: Health) -> Health:
        """One service used by several clients, such as OpenAI: what they know between them."""
        ok_at = max((record.ok_at for record in records if record.ok_at), default=None)
        failed = [record for record in records if record.failed_at]
        latest = max(failed, key=lambda record: record.failed_at, default=Health())
        return Health(ok_at, latest.failed_at, latest.problem)
