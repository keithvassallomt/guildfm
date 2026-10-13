"""Admin settings, kept in the database. (config.py is different: it comes from .env.)"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.models import Setting

DEFAULTS: dict[str, Any] = {
    "allow_explicit": True,
}


async def get_pref(db: AsyncSession, key: str) -> Any:
    row = await db.get(Setting, key)
    return row.value if row else DEFAULTS[key]


async def set_pref(db: AsyncSession, key: str, value: Any) -> None:
    if key not in DEFAULTS:
        raise KeyError(key)
    await db.merge(Setting(key=key, value=value))
    await db.commit()
