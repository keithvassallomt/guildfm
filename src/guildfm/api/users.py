"""User management for admins: list, add, change roles, reset passwords, delete."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.accounts import create_user, find_user, reset_password, temporary_password
from guildfm.api.schemas import NewUserIn, RoleIn, TemporaryPasswordOut, UserOut
from guildfm.auth import require
from guildfm.db import get_session
from guildfm.models import User
from guildfm.permissions import Permission

router = APIRouter(prefix="/users")
Db = Annotated[AsyncSession, Depends(get_session)]
Admin = Annotated[User, require(Permission.MANAGE_USERS)]


async def someone_else(user_id: int, admin: User, db: AsyncSession) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="There's no such user.")
    if user.id == admin.id:
        raise HTTPException(status_code=403, detail="Another admin has to change your account.")
    return user


@router.get("")
async def list_users(_: Admin, db: Db) -> list[UserOut]:
    users = await db.scalars(select(User).order_by(func.lower(User.display_name)))
    return [UserOut.model_validate(user) for user in users]


@router.post("", status_code=201)
async def add_user(body: NewUserIn, _: Admin, db: Db) -> TemporaryPasswordOut:
    if await find_user(db, body.username):
        raise HTTPException(status_code=409, detail="That username is taken.")
    password = temporary_password()
    try:
        user = await create_user(
            db,
            username=body.username,
            display_name=body.display_name,
            password=password,
            must_change_password=True,
        )
        await db.commit()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="That username is taken.") from None
    return TemporaryPasswordOut(user=UserOut.model_validate(user), temporary_password=password)


@router.patch("/{user_id}")
async def change_role(user_id: int, body: RoleIn, admin: Admin, db: Db) -> UserOut:
    user = await someone_else(user_id, admin, db)
    user.role = body.role
    await db.commit()
    return UserOut.model_validate(user)


@router.post("/{user_id}/reset-password")
async def reset(user_id: int, admin: Admin, db: Db, request: Request) -> TemporaryPasswordOut:
    user = await someone_else(user_id, admin, db)
    password = reset_password(user)
    await db.commit()
    await request.app.state.live.sign_out_user(user.id)
    return TemporaryPasswordOut(user=UserOut.model_validate(user), temporary_password=password)


@router.delete("/{user_id}", status_code=204)
async def delete(user_id: int, admin: Admin, db: Db, request: Request) -> None:
    user = await someone_else(user_id, admin, db)
    await db.delete(user)
    await db.commit()
    await request.app.state.live.sign_out_user(user_id)
