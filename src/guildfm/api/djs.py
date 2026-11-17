"""DJs, for the station editor to choose from: each can host any number of stations."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.auth import require
from guildfm.db import get_session
from guildfm.models import DJProfile, Station, StationDJ, User
from guildfm.permissions import Permission

router = APIRouter(prefix="/djs")
Db = Annotated[AsyncSession, Depends(get_session)]
Maker = Annotated[User, require(Permission.CREATE_STATIONS)]


class HostedOut(BaseModel):
    id: int
    name: str


class DJOut(BaseModel):
    id: int
    name: str
    personality: str
    voice: str
    pet_peeves: str
    soft_spots: str
    obsession: str
    stations: list[HostedOut]  # the stations they host, by name


@router.get("")
async def djs(_: Maker, db: Db) -> list[DJOut]:
    """Every DJ, by name, with the stations each hosts."""
    hosts = (await db.scalars(select(DJProfile).order_by(func.lower(DJProfile.name)))).all()
    hosting = await db.execute(
        select(StationDJ.dj_id, Station.id, Station.name)
        .join(Station, Station.id == StationDJ.station_id)
        .order_by(func.lower(Station.name))
    )
    stations: dict[int, list[HostedOut]] = {}
    for dj_id, station_id, name in hosting:
        stations.setdefault(dj_id, []).append(HostedOut(id=station_id, name=name))
    return [
        DJOut(
            id=host.id,
            name=host.name,
            personality=host.personality,
            voice=host.voice,
            pet_peeves=host.pet_peeves,
            soft_spots=host.soft_spots,
            obsession=host.obsession,
            stations=stations.get(host.id, []),
        )
        for host in hosts
    ]
