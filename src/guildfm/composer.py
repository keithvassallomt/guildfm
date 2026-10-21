"""The jingle generator: the AI writes descriptions of jingles, ElevenLabs' music model makes
them, and whoever looks after the jingles listens, then keeps each one or turns it down.

Each one with words is listened to once it's made: when OpenAI can't hear them in it, it's made
again, once.

What ElevenLabs makes is a draft, in the media folder's jingle drafts (left out of backups),
until it's kept, when it becomes a jingle straight away, or turned down. A round of drafts lasts
until the generator is done with it, so closing it part way loses nothing. Then the kept ones
stay jingles, the turned down ones are remembered by their descriptions so the AI steers clear
of them, and the rest are thrown away. A round nobody finished is done with after a day.
"""

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.ai import AIClient, AIError, object_schema
from guildfm.audio import level
from guildfm.jingles import folder as jingle_folder
from guildfm.models import (
    JINGLE_DRAFTS,
    DraftStatus,
    Jingle,
    JingleDraft,
    JingleKind,
    TurnedDownJingle,
)
from guildfm.prefs import get_pref
from guildfm.speech import Music, PromptRefused, SpeechClient, SpeechError, mp3_seconds, sang

log = logging.getLogger(__name__)

SHORTEST, LONGEST = 5, 15  # seconds a jingle can be asked for
ROUND = 6  # drafts in a round at most
AT_ONCE = 2  # drafts ElevenLabs makes side by side; it turns a third away as busy
REMEMBERED = 20  # earlier jingles of each sort, kept and turned down, that the AI is told about
MAX_PROMPT = 1000
DAY = 24 * 60 * 60
UNDECIDED = (DraftStatus.MAKING, DraftStatus.READY, DraftStatus.FAILED)
# On a draft that was made, when its words couldn't be heard in it, twice.
UNSUNG = "The words didn't come through, twice. Try again, or keep it as it is."

INSTRUCTIONS = (
    "You write radio jingles: short idents played between songs, which ElevenLabs' music model "
    "makes from your descriptions. Describe each one the way the model needs it: the genre and "
    "mood, the tempo, the instruments, how it starts and how it ends, and the words, in quotes, "
    'spelled the way they should sound ("Guild F M"). Every jingle has words, the name at '
    "least, sung, chanted or rapped and never spoken, since the model sings and tends to leave "
    "spoken lines out. Only a jingle you're told is instrumental has no words. Never name a "
    "real artist, band, song or album, or quote real lyrics: the model refuses those. Each "
    "description is one or two sentences, under 400 characters."
)


class ComposerError(Exception):
    """A draft that can't be changed that way. The message is fit to show people."""


@dataclass(frozen=True)
class Idea:
    name: str
    prompt: str
    seconds: int


@dataclass(frozen=True)
class Card:
    """A jingle in the generator's round, as it's being described."""

    text: str = ""
    instrumental: bool = False  # switched on by hand; the AI never makes one so itself


@dataclass(frozen=True)
class Owner:
    """Who the jingles are for, as the AI hears it: GuildFM, or one station as its editor has
    it, saved or not."""

    station_id: int | None
    name: str = ""
    description: str = ""
    dj_name: str = ""
    personality: str = ""


def ideas_schema() -> dict[str, Any]:
    jingle = object_schema(
        name={"type": "string", "description": "A short name for the list, two to four words."},
        description={"type": "string", "description": "What the music model makes."},
        seconds={"type": "integer", "description": f"From {SHORTEST} to {LONGEST}."},
    )
    return object_schema(jingles={"type": "array", "items": jingle})


def ideas_prompt(
    owner: Owner,
    about: str,
    kept: list[Jingle],
    turned_down: list[str],
    cards: list[Card],
    write: list[int],
) -> str:
    """What the AI is told: who the jingles are for, what's been made before, and the round so
    far, with the cards it's to write."""
    if owner.station_id is None:
        lines = [
            "These are system idents for GuildFM, the office radio that every AI station is "
            f"part of. What GuildFM is, in its admins' words: {about}"
        ]
    else:
        lines = [
            f'These are station idents for "{owner.name}", an AI station on GuildFM, the office '
            f"radio. What it plays: {owner.description}"
        ]
        if owner.dj_name:
            dj = f"Its DJ is {owner.dj_name}."
            lines.append(f"{dj} {owner.personality}".strip() if owner.personality else dj)
    if kept:
        lines += ["", "Made before and kept, so make the new ones different from these:"]
        for jingle in kept:
            sort = ", instrumental" if jingle.instrumental else ""
            lines.append(f"- {jingle.prompt} ({round(jingle.seconds)} seconds{sort})")
    if turned_down:
        lines += [
            "",
            "Made before and turned down, because people didn't like how they came out, so "
            "steer clear of these:",
        ]
        lines += [f"- {prompt}" for prompt in turned_down]
    lines += ["", f"This round has {len(cards)}:"]
    for n, card in enumerate(cards):
        text = card.text.strip()
        sort = ", an instrumental with no words" if card.instrumental else ""
        if n not in write:
            line = f"Written already{sort}: {text}" if text else "Not yet."
        elif text:
            line = (
                f"Write this one{sort}, building on what's there and keeping its idea and "
                f"anything it asks for: {text}"
            )
        else:
            line = f"Write this one{sort}."
        lines.append(f"{n + 1}. {line}")
    asked = len(write)
    lines += [
        "",
        f"Answer with the {asked} you're asked to write, in order, each different from the "
        f"others in the round and from what's been made before. Each is {SHORTEST} to "
        f"{LONGEST} seconds, long enough for its words to be sung clearly.",
    ]
    return "\n".join(lines)


def _scope(model, station_id: int | None):
    """Rows for a system ident (None) or for one station."""
    column = model.station_id
    return column.is_(None) if station_id is None else column == station_id


class Composer:
    def __init__(
        self,
        sessionmaker,
        ai: AIClient,
        speech: SpeechClient,
        media_dir: Path,
        loudness: float | None = None,
    ) -> None:
        self._sessions = sessionmaker
        self._ai = ai
        self._speech = speech
        self._media = media_dir
        self._loudness = loudness
        self._folder = media_dir / JINGLE_DRAFTS
        self._limit = asyncio.Semaphore(AT_ONCE)
        self._tasks: dict[int, asyncio.Task] = {}  # drafts being made, by id

    async def close(self) -> None:
        """Stop making drafts, before the database closes."""
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def settle(self) -> None:
        """Wait for the drafts being made. For tests."""
        await asyncio.gather(*self._tasks.values())

    async def recover(self) -> None:
        """At startup: drafts that were being made when GuildFM stopped never will be."""
        async with self._sessions() as db:
            stopped = await db.scalars(
                select(JingleDraft).where(JingleDraft.status == DraftStatus.MAKING)
            )
            for draft in stopped:
                draft.status = DraftStatus.FAILED
                draft.problem = "GuildFM restarted before this one was made. Try again."
            await db.commit()

    async def ideas(self, owner: Owner, cards: list[Card], write: list[int]) -> list[Idea]:
        """The AI's descriptions for the cards numbered in `write`, from 0, in that order. Raises
        AIError when it can't come up with them."""
        async with self._sessions() as db:
            about = await get_pref(db, "about") if owner.station_id is None else ""
            kept = list(
                await db.scalars(
                    select(Jingle)
                    .where(_scope(Jingle, owner.station_id), Jingle.prompt.is_not(None))
                    .order_by(Jingle.id.desc())
                    .limit(REMEMBERED)
                )
            )
            turned_down = list(
                await db.scalars(
                    select(TurnedDownJingle.prompt)
                    .where(_scope(TurnedDownJingle, owner.station_id))
                    .order_by(TurnedDownJingle.id.desc())
                    .limit(REMEMBERED)
                )
            )
        prompt = ideas_prompt(owner, about, kept[::-1], turned_down[::-1], cards, write)
        answer = await self._ai.json(INSTRUCTIONS, prompt, "jingle_ideas", ideas_schema())
        found = []
        for item in answer.get("jingles", []):
            text = str(item.get("description", "")).strip()[:MAX_PROMPT]
            if not text:
                continue
            seconds = item.get("seconds")
            found.append(
                Idea(
                    name=str(item.get("name", "")).strip()[:100] or "Jingle",
                    prompt=text,
                    seconds=min(LONGEST, max(SHORTEST, seconds if isinstance(seconds, int) else 8)),
                )
            )
        if len(found) < len(write):
            raise AIError("The AI didn't write them all. Try again.")
        return found[: len(write)]

    async def drafts(self, db: AsyncSession, station_id: int | None) -> list[JingleDraft]:
        """The round so far, for a system ident (None) or a station's own."""
        rows = await db.scalars(
            select(JingleDraft).where(_scope(JingleDraft, station_id)).order_by(JingleDraft.id)
        )
        return list(rows)

    async def made_before(self, db: AsyncSession, station_id: int | None) -> tuple[int, int]:
        """How many made here were kept, and how many turned down."""
        kept = await db.scalar(
            select(func.count())
            .select_from(Jingle)
            .where(_scope(Jingle, station_id), Jingle.prompt.is_not(None))
        )
        turned_down = await db.scalar(
            select(func.count())
            .select_from(TurnedDownJingle)
            .where(_scope(TurnedDownJingle, station_id))
        )
        return kept or 0, turned_down or 0

    async def make(
        self, station_id: int | None, name: str, prompt: str, length: int, instrumental: bool
    ) -> JingleDraft:
        """A new draft, which ElevenLabs makes in the background: a minute or so."""
        async with self._sessions() as db:
            if len(await self.drafts(db, station_id)) >= ROUND:
                raise ComposerError(f"That's {ROUND} already. Finish with these first.")
            draft = JingleDraft(
                station_id=station_id,
                name=name,
                prompt=prompt,
                length=length,
                instrumental=instrumental,
                created_at=time.time(),
            )
            db.add(draft)
            await db.commit()
        self._start(draft.id)
        return draft

    async def again(self, db: AsyncSession, draft: JingleDraft, prompt: str | None) -> None:
        """Make the draft again, from a new description if there is one."""
        if draft.status in (DraftStatus.KEPT, DraftStatus.TURNED_DOWN):
            raise ComposerError("Undo that first.")
        if draft.status == DraftStatus.MAKING:
            return
        self._forget(draft)
        draft.prompt = prompt or draft.prompt
        draft.status = DraftStatus.MAKING
        draft.seconds = draft.problem = draft.suggestion = None
        await db.commit()
        self._start(draft.id)

    async def decide(self, db: AsyncSession, draft: JingleDraft, status: DraftStatus) -> None:
        """Keep a made draft, which makes it a jingle at once, turn it down, or undo either."""
        if status == draft.status:
            return
        if status == DraftStatus.READY:
            await self._undo(db, draft)
        elif draft.status != DraftStatus.READY:
            raise ComposerError("That one isn't ready to keep or turn down.")
        elif status == DraftStatus.KEPT:
            await self._keep(db, draft)
        elif status == DraftStatus.TURNED_DOWN:
            draft.status = status
        else:
            raise ComposerError("A draft can only be kept, turned down, or put back.")
        await db.commit()

    async def rename(self, db: AsyncSession, draft: JingleDraft, name: str) -> None:
        """A new name, for the jingle too once it's kept."""
        draft.name = name
        if draft.jingle_id is not None:
            jingle = await db.get(Jingle, draft.jingle_id)
            if jingle is not None:
                jingle.name = name
        await db.commit()

    async def leave_out(self, db: AsyncSession, draft: JingleDraft) -> None:
        """Throw away a draft that isn't kept: one ElevenLabs refused, say."""
        if draft.status == DraftStatus.KEPT:
            raise ComposerError("Undo that first.")
        self._drop(draft)
        await db.delete(draft)
        await db.commit()

    async def done(self, db: AsyncSession, station_id: int | None) -> None:
        """The round is over: kept drafts stay jingles, turned down ones are remembered, and the
        rest are thrown away."""
        for draft in await self.drafts(db, station_id):
            await self._finish(db, draft)
        await db.commit()

    async def clear_old(self, now: float | None = None) -> None:
        """Finish drafts over a day old, from rounds nobody finished. Daily."""
        cutoff = (now if now is not None else time.time()) - DAY
        async with self._sessions() as db:
            old = await db.scalars(select(JingleDraft).where(JingleDraft.created_at < cutoff))
            for draft in old:
                await self._finish(db, draft)
            await db.commit()

    def forget_station(self, drafts: list[JingleDraft]) -> None:
        """A station being deleted: its drafts' files. Their rows go with it."""
        for draft in drafts:
            self._drop(draft)

    def url(self, draft: JingleDraft) -> str | None:
        """Where the browser plays it, once made."""
        return f"/media/{JINGLE_DRAFTS}/{draft.file}" if draft.file else None

    def _start(self, draft_id: int) -> None:
        self._tasks[draft_id] = asyncio.create_task(self._quietly(draft_id))

    async def _quietly(self, draft_id: int) -> None:
        try:
            await self._make(draft_id)
        except Exception:
            log.exception("Making a jingle failed")
            async with self._sessions() as db:
                draft = await db.get(JingleDraft, draft_id)
                if draft is not None and draft.status == DraftStatus.MAKING:
                    draft.status = DraftStatus.FAILED
                    draft.problem = "Something went wrong making this one. Try again."
                    await db.commit()
        finally:
            if self._tasks.get(draft_id) is asyncio.current_task():
                del self._tasks[draft_id]

    async def _make(self, draft_id: int) -> None:
        async with self._limit:
            async with self._sessions() as db:
                draft = await db.get(JingleDraft, draft_id)
                if draft is None or draft.status != DraftStatus.MAKING:
                    return
                prompt, length, instrumental = draft.prompt, draft.length, draft.instrumental
            data, problem, suggestion = None, None, None
            try:
                music = await self._speech.compose(prompt, length, instrumental)
                if not await self._sang(music):
                    log.info("The words didn't come through in a jingle, so it's made again")
                    music = await self._speech.compose(prompt, length, instrumental)
                    if not await self._sang(music):
                        problem = UNSUNG
                data = await level(music.data, self._loudness)
                if not mp3_seconds(data):
                    raise SpeechError("ElevenLabs sent something that isn't an MP3. Try again.")
            except PromptRefused as error:
                data, problem, suggestion = None, str(error), error.suggestion
            except SpeechError as error:
                data, problem = None, str(error)
        file = None
        if data is not None:
            self._folder.mkdir(parents=True, exist_ok=True)
            file = f"{secrets.token_urlsafe(12)}.mp3"
            (self._folder / file).write_bytes(data)
        async with self._sessions() as db:
            draft = await db.get(JingleDraft, draft_id)
            if draft is None or draft.status != DraftStatus.MAKING or draft.prompt != prompt:
                # Thrown away, or asked for again from a new description, meanwhile.
                if file:
                    (self._folder / file).unlink(missing_ok=True)
                return
            if file:
                draft.status, draft.file, draft.seconds = DraftStatus.READY, file, mp3_seconds(data)
                draft.problem = problem
            else:
                draft.status, draft.problem, draft.suggestion = (
                    DraftStatus.FAILED,
                    (problem or "")[:300],
                    suggestion[:MAX_PROMPT] if suggestion else None,
                )
            await db.commit()

    async def _sang(self, music: Music) -> bool:
        """Whether the words to be sung can be heard in it. Yes for no words, or when OpenAI
        can't listen just now: then it's left to the ears."""
        if not music.words:
            return True
        try:
            return sang(await self._speech.heard(music.data), music.words)
        except SpeechError as error:
            log.warning("Couldn't listen for the words in a jingle: %s", error)
            return True

    async def _keep(self, db: AsyncSession, draft: JingleDraft) -> None:
        place = jingle_folder(self._media)
        place.mkdir(parents=True, exist_ok=True)
        (self._folder / draft.file).replace(place / draft.file)
        jingle = Jingle(
            kind=JingleKind.STATION if draft.station_id else JingleKind.SYSTEM,
            station_id=draft.station_id,
            name=draft.name,
            file=draft.file,
            seconds=draft.seconds,
            created_at=time.time(),
            prompt=draft.prompt,
            instrumental=draft.instrumental,
        )
        db.add(jingle)
        await db.flush()
        draft.status, draft.file, draft.jingle_id = DraftStatus.KEPT, None, jingle.id

    async def _undo(self, db: AsyncSession, draft: JingleDraft) -> None:
        if draft.status == DraftStatus.TURNED_DOWN:
            draft.status = DraftStatus.READY
            return
        if draft.status != DraftStatus.KEPT:
            raise ComposerError("There's nothing to undo.")
        jingle = await db.get(Jingle, draft.jingle_id) if draft.jingle_id else None
        if jingle is None:
            raise ComposerError("That jingle has been removed from the list already.")
        self._folder.mkdir(parents=True, exist_ok=True)
        (jingle_folder(self._media) / jingle.file).replace(self._folder / jingle.file)
        draft.status, draft.file, draft.jingle_id = DraftStatus.READY, jingle.file, None
        await db.delete(jingle)

    async def _finish(self, db: AsyncSession, draft: JingleDraft) -> None:
        if draft.status == DraftStatus.TURNED_DOWN:
            db.add(
                TurnedDownJingle(
                    station_id=draft.station_id, prompt=draft.prompt, turned_down_at=time.time()
                )
            )
        if draft.status != DraftStatus.KEPT:
            self._drop(draft)
        await db.delete(draft)

    def _drop(self, draft: JingleDraft) -> None:
        """Stop making it and delete its file."""
        task = self._tasks.pop(draft.id, None)
        if task is not None:
            task.cancel()
        self._forget(draft)

    def _forget(self, draft: JingleDraft) -> None:
        if draft.file:
            (self._folder / draft.file).unlink(missing_ok=True)
            draft.file = None
