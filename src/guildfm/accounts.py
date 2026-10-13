"""Creating accounts, the seeded admin, and temporary passwords."""

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guildfm.auth import hash_password
from guildfm.config import Settings
from guildfm.models import Role, User

# Short, unambiguous words, so a temporary password is easy to read out or pass on.
WORDS = (
    "amber apple aspen badge basil beach berry birch blaze bloom brass brick brook cabin cedar "
    "chalk cider cloud clove coast comet coral crane creek crisp delta drift dune ember fable "
    "fern fjord flint frost gecko glade grain grove harbor hazel heron honey ivory jade jolly "
    "kayak koala lemon lilac linen lotus lunar maple marsh meadow mint misty moss night nova "
    "oak ocean olive opal orbit otter panda pearl pebble pine plum polar pond poppy quail quartz "
    "raven reef ridge river robin rowan sage sandy shell slate solar spruce storm sunny swift "
    "thyme tidal toast topaz tulip velvet violet walnut willow winter wren yarrow zephyr"
).split()


def temporary_password() -> str:
    return f"{secrets.choice(WORDS)}-{secrets.choice(WORDS)}-{secrets.randbelow(90) + 10}"


async def find_user(db: AsyncSession, username: str) -> User | None:
    return await db.scalar(select(User).where(User.username == username.strip().lower()))


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    display_name: str,
    password: str,
    role: Role = Role.USER,
    must_change_password: bool = False,
) -> User:
    user = User(
        username=username.strip().lower(),
        display_name=display_name,
        password_hash=hash_password(password),
        role=role,
        must_change_password=must_change_password,
    )
    db.add(user)
    await db.flush()
    return user


def reset_password(user: User) -> str:
    """Give the user a temporary password they must replace, and sign them out everywhere."""
    password = temporary_password()
    user.password_hash = hash_password(password)
    user.must_change_password = True
    user.session_version += 1
    return password


async def seed_admin(db: AsyncSession, settings: Settings) -> None:
    """Create the admin account from .env on first start. An existing account is left alone."""
    username = settings.guildfm_admin_username
    if await find_user(db, username) is None:
        await create_user(
            db,
            username=username,
            display_name=username.strip().capitalize(),
            password=settings.guildfm_admin_password.get_secret_value(),
            role=Role.ADMIN,
        )
        await db.commit()
