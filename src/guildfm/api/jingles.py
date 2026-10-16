"""Jingles: admins look after GuildFM's station idents, and whoever makes stations looks after
each station's show idents. Uploaded as MP3s, sent as the request body."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.auth import ActiveUser
from guildfm.db import get_session
from guildfm.jingles import JingleError, add_jingle, forget
from guildfm.models import Jingle, JingleKind, Station, StationKind, User
from guildfm.permissions import Permission, can

router = APIRouter(prefix="/jingles")
Db = Annotated[AsyncSession, Depends(get_session)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


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


def media(request: Request) -> Path:
    return request.app.state.settings.data_dir / "media"


async def _allowed(db: AsyncSession, user: User, station_id: int | None) -> None:
    """Station idents are for admins, a station's show idents for whoever makes stations."""
    needs = Permission.CREATE_STATIONS if station_id else Permission.CHANGE_SETTINGS
    if not can(user.role, needs):
        raise HTTPException(403, "You don't have permission to do that.")
    if station_id:
        station = await db.get(Station, station_id)
        if station is None:
            raise HTTPException(404, "That station doesn't exist any more.")
        if station.kind == StationKind.AI_PICKS:
            raise HTTPException(409, "AI picks plays GuildFM's station idents only.")


@router.get("")
async def jingles(user: ActiveUser, db: Db, station_id: int | None = None) -> list[JingleOut]:
    """GuildFM's station idents, or with `station_id`, that station's show idents."""
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
    """Add an MP3 as a station ident, or with `station_id`, a show ident for that station."""
    await _allowed(db, user, station_id)
    try:
        jingle = add_jingle(db, media(request), await request.body(), name, station_id)
    except JingleError as error:
        raise HTTPException(415, str(error)) from None
    await db.commit()
    return JingleOut.of(jingle)


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
