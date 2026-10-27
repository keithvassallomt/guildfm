"""Signing up, signing in and out, and the signed-in user's own profile."""

import secrets
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.accounts import create_user, find_user
from guildfm.api.schemas import MeOut, PasswordIn, ProfileIn, RegisterIn, SignInIn
from guildfm.auth import (
    ActiveUser,
    CurrentUser,
    hash_password,
    password_matches,
    sign_in,
    sign_out,
)
from guildfm.db import get_session
from guildfm.models import AVATARS, Role, User
from guildfm.permissions import ROLE_PERMISSIONS, Permission

router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_session)]

# The browser shrinks photos to a small square first, so this is generous.
MAX_AVATAR = 1024 * 1024


def _picture(data: bytes) -> str | None:
    """The file extension for a JPEG, PNG or WebP picture, from its first bytes."""
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def avatars(request: Request) -> Path:
    return request.app.state.settings.data_dir / "media" / AVATARS


def forget_avatar(request: Request, user: User) -> None:
    """Delete the user's photo file, if they have one."""
    if user.avatar:
        (avatars(request) / user.avatar).unlink(missing_ok=True)
        user.avatar = None


@router.post("/auth/register", status_code=201)
async def register(body: RegisterIn, request: Request, db: Db) -> MeOut:
    if await find_user(db, body.username):
        raise HTTPException(status_code=409, detail="That username is taken.")
    try:
        user = await create_user(
            db, username=body.username, display_name=body.display_name, password=body.password
        )
        await db.commit()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="That username is taken.") from None
    sign_in(request, user)
    return MeOut.of(user)


@router.post("/auth/login")
async def login(body: SignInIn, request: Request, db: Db) -> MeOut:
    user = await find_user(db, body.username)
    if not password_matches(user, body.password):
        raise HTTPException(status_code=401, detail="That username and password don't match.")
    sign_in(request, user)
    return MeOut.of(user)


@router.post("/auth/logout", status_code=204)
async def logout(request: Request) -> None:
    sign_out(request)


@router.get("/me")
async def me(user: CurrentUser) -> MeOut:
    return MeOut.of(user)


@router.get("/roles")
async def roles(_: ActiveUser) -> dict[Role, list[Permission]]:
    """What each role may do, so the help can be read as another role would see it."""
    return {
        role: [permission for permission in Permission if permission in allowed]
        for role, allowed in ROLE_PERMISSIONS.items()
    }


@router.patch("/me")
async def update_me(body: ProfileIn, user: ActiveUser, db: Db) -> MeOut:
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.announce_requests is not None:
        user.announce_requests = body.announce_requests
    await db.commit()
    return MeOut.of(user)


@router.put("/me/avatar")
async def set_avatar(request: Request, user: ActiveUser, db: Db) -> MeOut:
    """A photo for beside your name, sent as the request body."""
    data = await request.body()
    if len(data) > MAX_AVATAR:
        raise HTTPException(413, "That picture is too big.")
    kind = _picture(data)
    if kind is None:
        raise HTTPException(415, "That isn't a picture GuildFM can show. Try a JPEG or PNG.")
    folder = avatars(request)
    folder.mkdir(parents=True, exist_ok=True)
    # A new name each time, so browsers don't show the old photo from their cache.
    name = f"{secrets.token_urlsafe(12)}{kind}"
    (folder / name).write_bytes(data)
    forget_avatar(request, user)
    user.avatar = name
    await db.commit()
    await request.app.state.queue.changed()
    return MeOut.of(user)


@router.delete("/me/avatar")
async def remove_avatar(request: Request, user: ActiveUser, db: Db) -> MeOut:
    forget_avatar(request, user)
    await db.commit()
    await request.app.state.queue.changed()
    return MeOut.of(user)


@router.post("/me/password")
async def choose_password(body: PasswordIn, request: Request, user: CurrentUser, db: Db) -> MeOut:
    """Replace a temporary password. Anyone else asks an admin for a reset."""
    if not user.must_change_password:
        raise HTTPException(status_code=403, detail="Ask an admin to reset your password.")
    user.password_hash = hash_password(body.password)
    user.must_change_password = False
    # Sessions opened with the temporary password stop working.
    user.session_version += 1
    await db.commit()
    sign_in(request, user)
    return MeOut.of(user)
