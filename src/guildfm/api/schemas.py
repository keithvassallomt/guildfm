import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict
from pydantic_core import PydanticCustomError

from guildfm.models import Role, User
from guildfm.permissions import ROLE_PERMISSIONS, Permission

_USERNAME = re.compile(r"[a-z0-9._-]{3,32}")


def _username(value: str) -> str:
    value = value.strip().lower()
    if not _USERNAME.fullmatch(value):
        raise PydanticCustomError(
            "username",
            "Usernames are 3 to 32 letters, numbers, dots, dashes or underscores.",
        )
    return value


def _display_name(value: str) -> str:
    value = " ".join(value.split())
    if not 1 <= len(value) <= 40:
        raise PydanticCustomError("display_name", "Display names are 1 to 40 characters.")
    return value


def _password(value: str) -> str:
    if len(value) < 8:
        raise PydanticCustomError("password", "Use at least 8 characters for your password.")
    if len(value) > 128:
        raise PydanticCustomError("password", "Passwords can be at most 128 characters.")
    return value


Username = Annotated[str, AfterValidator(_username)]
DisplayName = Annotated[str, AfterValidator(_display_name)]
NewPassword = Annotated[str, AfterValidator(_password)]


class RegisterIn(BaseModel):
    username: Username
    display_name: DisplayName
    password: NewPassword


class SignInIn(BaseModel):
    username: str
    password: str


class ProfileIn(BaseModel):
    display_name: DisplayName | None = None
    announce_requests: bool | None = None


class PasswordIn(BaseModel):
    password: NewPassword


class NewUserIn(BaseModel):
    username: Username
    display_name: DisplayName


class RoleIn(BaseModel):
    role: Role


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: Role
    announce_requests: bool
    must_change_password: bool


class MeOut(UserOut):
    """The signed-in user, plus what they're allowed to do, so the UI needn't repeat the rules."""

    permissions: list[Permission]

    @classmethod
    def of(cls, user: User) -> MeOut:
        return cls(
            **UserOut.model_validate(user).model_dump(),
            permissions=sorted(ROLE_PERMISSIONS[user.role]),
        )


class TemporaryPasswordOut(BaseModel):
    user: UserOut
    temporary_password: str


class TrackOut(BaseModel):
    id: str
    title: str
    artists: str
    album: str
    duration: int  # seconds
    explicit: bool
    art_url: str | None

    @classmethod
    def of(cls, track) -> TrackOut:
        """From a stored track or a Spotify search result; both carry the same fields."""
        return cls(
            id=track.id,
            title=track.title,
            artists=track.artists,
            album=track.album,
            duration=round(track.duration_ms / 1000),
            explicit=track.explicit,
            art_url=track.art_url,
        )
