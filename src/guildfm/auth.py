"""Passwords, sign-in sessions, and the dependencies that guard API routes."""

from typing import Annotated, Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.db import get_session
from guildfm.models import User
from guildfm.permissions import Permission, can

SESSION_KEY = "user"

_hasher = PasswordHasher()
# Checked when a username doesn't exist, so a failed sign-in takes the same time either way.
_DUMMY_HASH = _hasher.hash("guildfm-timing-guard")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def password_matches(user: User | None, password: str) -> bool:
    try:
        _hasher.verify(user.password_hash if user else _DUMMY_HASH, password)
    except VerifyMismatchError, InvalidHashError:
        return False
    return user is not None


def sign_in(request: Request, user: User) -> None:
    request.session[SESSION_KEY] = {"id": user.id, "v": user.session_version}


def sign_out(request: Request) -> None:
    request.session.clear()


async def session_user(session: dict[str, Any], db: AsyncSession) -> User | None:
    data = session.get(SESSION_KEY)
    if not isinstance(data, dict):
        return None
    user = await db.get(User, data.get("id"))
    if user is None or user.session_version != data.get("v"):
        return None
    return user


async def current_user(request: Request, db: Annotated[AsyncSession, Depends(get_session)]) -> User:
    """The signed-in user, including one who still has to replace a temporary password."""
    user = await session_user(request.session, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in first.")
    return user


async def active_user(user: Annotated[User, Depends(current_user)]) -> User:
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Choose a new password first.")
    return user


def require(permission: Permission):
    """Use as `Annotated[User, require(Permission.X)]` to guard a route."""

    async def check(user: Annotated[User, Depends(active_user)]) -> User:
        if not can(user.role, permission):
            raise HTTPException(status_code=403, detail="You don't have permission to do that.")
        return user

    return Depends(check)


CurrentUser = Annotated[User, Depends(current_user)]
ActiveUser = Annotated[User, Depends(active_user)]
