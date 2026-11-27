"""The kiosk: the touchscreen in the office, signed in as a kiosk account.

It counts as one person when requests take turns, and has no request cap. It has places
instead (a setting): each request takes one, and one that starts playing or leaves the queue
gives it back. Taking the last starts a break (a setting) when it can't add or vote; after it,
every place is free again. A request can be taken back for UNDO_SECONDS after it's added, and
nothing else can be removed. Each tap on a thumb is a vote, up to VOTES each way on a song.
"""

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.models import EntryState, KioskVote, QueueEntry, Role, User
from guildfm.prefs import get_pref

# The most the kiosk counts for each way on one song: one short of the thumbs-down limit of 3,
# so on its own it can never take a request out.
VOTES = 2
UNDO_SECONDS = 10
# A request can still be taken back this long after the screen stops offering it, for a slow
# network or a late tap.
UNDO_GRACE = 2
ON_BREAK = "The kiosk is on a break. Try again when the countdown ends."


def is_kiosk(user: User) -> bool:
    return user.role == Role.KIOSK


@dataclass(frozen=True)
class Places:
    total: int
    used: int
    break_until: float | None  # when its break ends, while it's on one

    @property
    def left(self) -> int:
        return max(0, self.total - self.used)


async def places(db: AsyncSession, kiosk: User, now: float) -> Places:
    """Where the kiosk stands. A break that's over ends here: the caller commits."""
    if kiosk.kiosk_break_until is not None and now >= kiosk.kiosk_break_until:
        kiosk.kiosk_since, kiosk.kiosk_break_until = kiosk.kiosk_break_until, None
    used = await db.scalar(
        select(func.count())
        .select_from(QueueEntry)
        .where(
            QueueEntry.requested_by == kiosk.id,
            QueueEntry.state.in_((EntryState.WAITING, EntryState.NEXT)),
            QueueEntry.added_at >= kiosk.kiosk_since,
        )
    )
    return Places(await get_pref(db, "kiosk_places"), used or 0, kiosk.kiosk_break_until)


async def check_not_on_break(db: AsyncSession, kiosk: User, now: float) -> Places:
    state = await places(db, kiosk, now)
    await db.commit()
    if state.break_until is not None:
        raise HTTPException(409, ON_BREAK)
    return state


async def check_room(db: AsyncSession, kiosk: User, now: float) -> None:
    """Before a request goes in: not on a break, and a place free. (Places can run out without a
    break when an admin lowers the setting.)"""
    state = await check_not_on_break(db, kiosk, now)
    if state.left == 0:
        raise HTTPException(409, "The kiosk's places are all taken. Try again once one has played.")


async def after_request(db: AsyncSession, kiosk: User, now: float) -> bool:
    """A request just went in: taking the last place starts a break. True if it did."""
    state = await places(db, kiosk, now)
    if state.break_until is None and state.used >= state.total:
        kiosk.kiosk_break_until = now + await get_pref(db, "kiosk_break_minutes") * 60
        await db.commit()
        return True
    return False


def check_undo(entry: QueueEntry, now: float) -> None:
    if now > entry.added_at + UNDO_SECONDS + UNDO_GRACE:
        raise HTTPException(409, "It's too late to take that one back.")


async def vote(db: AsyncSession, kiosk: User, entry_id: int, value: int) -> None:
    """One more thumb from the kiosk on a song. The caller commits."""
    if value == 0:
        raise HTTPException(409, "The kiosk can't take a vote back.")
    row = await db.get(KioskVote, (entry_id, kiosk.id))
    if row is None:
        row = KioskVote(entry_id=entry_id, user_id=kiosk.id, up=0, down=0)
        db.add(row)
    if value > 0:
        if row.up >= VOTES:
            raise HTTPException(409, "The kiosk has given that song both its thumbs up.")
        row.up += 1
    else:
        if row.down >= VOTES:
            raise HTTPException(409, "The kiosk has given that song both its thumbs down.")
        row.down += 1


async def votes_of(db: AsyncSession, kiosk: User) -> dict[int, tuple[int, int]]:
    """The kiosk's thumbs up and down on each song it's voted on."""
    rows = await db.execute(
        select(KioskVote.entry_id, KioskVote.up, KioskVote.down).where(
            KioskVote.user_id == kiosk.id
        )
    )
    return {entry_id: (up, down) for entry_id, up, down in rows}
