"""Signing up, signing in and out, and the signed-in user's own profile."""

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

router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_session)]


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


@router.patch("/me")
async def update_me(body: ProfileIn, user: ActiveUser, db: Db) -> MeOut:
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.announce_requests is not None:
        user.announce_requests = body.announce_requests
    await db.commit()
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
