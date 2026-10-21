"""Jingles: admins look after the system idents, GuildFM's own, and whoever makes stations looks
after each station's station idents. Uploaded as MP3s, sent as the request body, or made in the
jingle generator: the AI writes descriptions, ElevenLabs makes drafts from them, and each draft
is kept or turned down (see composer.py)."""

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, StringConstraints, model_validator
from pydantic_core import PydanticCustomError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.ai import AIError
from guildfm.audio import level
from guildfm.auth import ActiveUser
from guildfm.composer import LONGEST, MAX_PROMPT, ROUND, SHORTEST, Card, ComposerError, Owner
from guildfm.db import get_session
from guildfm.jingles import JingleError, add_jingle, forget
from guildfm.models import DraftStatus, Jingle, JingleDraft, JingleKind, Station, StationKind, User
from guildfm.permissions import Permission, can

router = APIRouter(prefix="/jingles")
Db = Annotated[AsyncSession, Depends(get_session)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Prompt = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_PROMPT)
]


class JingleOut(BaseModel):
    id: int
    kind: JingleKind
    station_id: int | None
    name: str
    seconds: float
    url: str  # for the browser to play

    @classmethod
    def of(cls, jingle: Jingle) -> JingleOut:
        return cls(
            id=jingle.id,
            kind=jingle.kind,
            station_id=jingle.station_id,
            name=jingle.name,
            seconds=round(jingle.seconds, 1),
            url=jingle.url,
        )


class StationAsEdited(BaseModel):
    """A station as its editor has it, saved or not, for the AI writing its station idents."""

    name: Name
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)
    ]
    dj_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] = ""
    personality: Annotated[str, StringConstraints(strip_whitespace=True, max_length=600)] = ""


class CardIn(BaseModel):
    """A jingle in the round as it's being described."""

    text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_PROMPT)] = ""
    instrumental: bool = False  # switched on by hand


class IdeasIn(BaseModel):
    station_id: int | None = None  # None for system idents
    station: StationAsEdited | None = None  # the editor's details; else the saved ones
    cards: list[CardIn] = Field(min_length=1, max_length=ROUND)  # every card in the round
    write: list[int] = Field(min_length=1, max_length=ROUND)  # the ones to write, from 0

    @model_validator(mode="after")
    def writes_cards_there_are(self) -> IdeasIn:
        if len(set(self.write)) != len(self.write) or any(
            not 0 <= n < len(self.cards) for n in self.write
        ):
            raise PydanticCustomError("write", "Those aren't cards in the round.")
        return self


class IdeaOut(BaseModel):
    name: str
    prompt: str
    seconds: int


class DraftIn(BaseModel):
    station_id: int | None = None  # None for a system ident
    name: Name
    prompt: Prompt
    length: int = Field(ge=SHORTEST, le=LONGEST)
    instrumental: bool = False


class DraftChange(BaseModel):
    name: Name | None = None
    # Keep it, turn it down, or "ready" to undo either.
    status: Literal["kept", "turned_down", "ready"] | None = None


class AgainIn(BaseModel):
    prompt: Prompt | None = None  # a new description, for one ElevenLabs refused, say


class DraftOut(BaseModel):
    id: int
    station_id: int | None
    name: str
    prompt: str
    length: int  # the seconds asked for
    instrumental: bool
    status: DraftStatus
    seconds: float | None  # how long it plays, once made
    url: str | None  # for the browser to play, once made
    problem: str | None  # why ElevenLabs couldn't make it, or what's wrong with one it made
    suggestion: str | None  # ElevenLabs' own wording, when it refused the description


class RoundOut(BaseModel):
    drafts: list[DraftOut]
    # What the AI knows of from before: jingles made here and kept, and ones turned down.
    kept: int
    turned_down: int


def media(request: Request) -> Path:
    return request.app.state.settings.data_dir / "media"


async def _draft_out(db: AsyncSession, request: Request, draft: JingleDraft) -> DraftOut:
    url = request.app.state.composer.url(draft)
    if draft.status == DraftStatus.KEPT and draft.jingle_id is not None:
        jingle = await db.get(Jingle, draft.jingle_id)
        url = jingle.url if jingle else None
    return DraftOut(
        id=draft.id,
        station_id=draft.station_id,
        name=draft.name,
        prompt=draft.prompt,
        length=draft.length,
        instrumental=draft.instrumental,
        status=draft.status,
        seconds=round(draft.seconds, 1) if draft.seconds else None,
        url=url,
        problem=draft.problem,
        suggestion=draft.suggestion,
    )


async def _draft(db: AsyncSession, user: User, draft_id: int) -> JingleDraft:
    draft = await db.get(JingleDraft, draft_id)
    if draft is None:
        raise HTTPException(404, "That jingle isn't in the generator any more.")
    await _allowed(db, user, draft.station_id)
    return draft


async def _allowed(db: AsyncSession, user: User, station_id: int | None) -> None:
    """System idents are for admins, a station's own idents for whoever makes stations."""
    needs = Permission.CREATE_STATIONS if station_id else Permission.CHANGE_SETTINGS
    if not can(user.role, needs):
        raise HTTPException(403, "You don't have permission to do that.")
    if station_id:
        station = await db.get(Station, station_id)
        if station is None:
            raise HTTPException(404, "That station doesn't exist any more.")
        if station.kind == StationKind.AI_PICKS:
            raise HTTPException(409, "AI picks plays the system idents only.")


@router.get("")
async def jingles(user: ActiveUser, db: Db, station_id: int | None = None) -> list[JingleOut]:
    """The system idents, or with `station_id`, that station's station idents."""
    await _allowed(db, user, station_id)
    rows = await db.scalars(
        select(Jingle).where(Jingle.station_id == station_id).order_by(Jingle.id)
        if station_id
        else select(Jingle).where(Jingle.station_id.is_(None)).order_by(Jingle.id)
    )
    return [JingleOut.of(jingle) for jingle in rows]


@router.post("", status_code=201)
async def upload(
    request: Request,
    user: ActiveUser,
    db: Db,
    name: Annotated[Name, Query()],
    station_id: int | None = None,
) -> JingleOut:
    """Add an MP3 as a system ident, or with `station_id`, a station ident for that station. It's
    evened out to the same loudness as the voices."""
    await _allowed(db, user, station_id)
    data = await level(await request.body(), request.app.state.settings.audio_loudness)
    try:
        jingle = add_jingle(db, media(request), data, name, station_id)
    except JingleError as error:
        raise HTTPException(415, str(error)) from None
    await db.commit()
    return JingleOut.of(jingle)


@router.post("/ideas")
async def ideas(body: IdeasIn, user: ActiveUser, request: Request, db: Db) -> list[IdeaOut]:
    """The AI's descriptions for the cards in `write`, in that order, knowing the rest of the
    round and the jingles made before."""
    await _allowed(db, user, body.station_id)
    owner = Owner(None)
    if body.station_id:
        station = await db.get(Station, body.station_id)
        asked = body.station or StationAsEdited(
            name=station.name,
            description=station.description,
            dj_name=station.dj_name,
            personality=station.personality,
        )
        owner = Owner(
            body.station_id, asked.name, asked.description, asked.dj_name, asked.personality
        )
    try:
        cards = [Card(card.text, card.instrumental) for card in body.cards]
        found = await request.app.state.composer.ideas(owner, cards, body.write)
    except AIError as error:
        raise HTTPException(502, str(error)) from None
    return [IdeaOut(**vars(idea)) for idea in found]


@router.get("/drafts")
async def drafts(
    user: ActiveUser, request: Request, db: Db, station_id: int | None = None
) -> RoundOut:
    """The generator's round so far: system idents, or with `station_id`, that station's."""
    await _allowed(db, user, station_id)
    composer = request.app.state.composer
    found = await composer.drafts(db, station_id)
    kept, turned_down = await composer.made_before(db, station_id)
    return RoundOut(
        drafts=[await _draft_out(db, request, draft) for draft in found],
        kept=kept,
        turned_down=turned_down,
    )


@router.post("/drafts", status_code=201)
async def make(body: DraftIn, user: ActiveUser, request: Request, db: Db) -> DraftOut:
    """A new draft from a description. ElevenLabs makes it in the background, in a minute or so;
    the round shows when it's ready."""
    await _allowed(db, user, body.station_id)
    if not request.app.state.speech.eleven_ready:
        raise HTTPException(409, "ElevenLabs isn't set up. Add ELEVENLABS_API_KEY to .env.")
    try:
        draft = await request.app.state.composer.make(
            body.station_id, body.name, body.prompt, body.length, body.instrumental
        )
    except ComposerError as error:
        raise HTTPException(409, str(error)) from None
    return await _draft_out(db, request, draft)


@router.post("/drafts/done", status_code=204)
async def done(
    user: ActiveUser, request: Request, db: Db, station_id: int | None = None
) -> Response:
    """The round is over: kept ones stay, turned down ones are remembered for the AI, and the
    rest are thrown away."""
    await _allowed(db, user, station_id)
    await request.app.state.composer.done(db, station_id)
    return Response(status_code=204)


@router.patch("/drafts/{draft_id}")
async def change_draft(
    draft_id: int, body: DraftChange, user: ActiveUser, request: Request, db: Db
) -> DraftOut:
    """Rename a draft, keep it (it joins the jingles straight away), turn it down, or undo."""
    draft = await _draft(db, user, draft_id)
    composer = request.app.state.composer
    try:
        if body.name is not None:
            await composer.rename(db, draft, body.name)
        if body.status is not None:
            await composer.decide(db, draft, DraftStatus(body.status))
    except ComposerError as error:
        raise HTTPException(409, str(error)) from None
    return await _draft_out(db, request, draft)


@router.post("/drafts/{draft_id}/again")
async def again(
    draft_id: int, user: ActiveUser, request: Request, db: Db, body: AgainIn | None = None
) -> DraftOut:
    """Make a draft again, from a new description if one's given."""
    draft = await _draft(db, user, draft_id)
    try:
        await request.app.state.composer.again(db, draft, body.prompt if body else None)
    except ComposerError as error:
        raise HTTPException(409, str(error)) from None
    return await _draft_out(db, request, draft)


@router.delete("/drafts/{draft_id}", status_code=204)
async def leave_out(draft_id: int, user: ActiveUser, request: Request, db: Db) -> Response:
    draft = await _draft(db, user, draft_id)
    try:
        await request.app.state.composer.leave_out(db, draft)
    except ComposerError as error:
        raise HTTPException(409, str(error)) from None
    return Response(status_code=204)


@router.delete("/{jingle_id}", status_code=204)
async def delete(jingle_id: int, request: Request, user: ActiveUser, db: Db) -> Response:
    jingle = await db.get(Jingle, jingle_id)
    if jingle is None:
        raise HTTPException(404, "That jingle doesn't exist any more.")
    await _allowed(db, user, jingle.station_id)
    forget(media(request), jingle)
    await db.delete(jingle)
    await db.commit()
    return Response(status_code=204)
