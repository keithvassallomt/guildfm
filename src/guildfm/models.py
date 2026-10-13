from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for every table. Alembic reads its metadata to generate migrations."""


def enum_values(enum: type[StrEnum]) -> list[str]:
    """Store enums by value ("curator"), not by member name ("CURATOR")."""
    return [member.value for member in enum]


class Role(StrEnum):
    USER = "user"
    CURATOR = "curator"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stored in lower case; sign-in is case-insensitive.
    username: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(40))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(
        Enum(Role, native_enum=False, length=16, values_callable=enum_values),
        default=Role.USER,
    )
    announce_requests: Mapped[bool] = mapped_column(default=True)
    must_change_password: Mapped[bool] = mapped_column(default=False)
    # Part of every session cookie. Bumping it signs the user out everywhere.
    session_version: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Track(Base):
    """Spotify track details, kept so the queue and play history needn't ask Spotify again."""

    __tablename__ = "tracks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # Spotify's track id
    title: Mapped[str] = mapped_column(String(300))
    artists: Mapped[str] = mapped_column(String(300))
    album: Mapped[str] = mapped_column(String(300))
    duration_ms: Mapped[int]
    explicit: Mapped[bool]
    art_url: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Setting(Base):
    """One admin setting. Missing settings fall back to the defaults in prefs.py."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class SpotifyAccount(Base):
    """The one Spotify account connected for playlist import. Its row id is always 1."""

    __tablename__ = "spotify_account"

    id: Mapped[int] = mapped_column(primary_key=True)
    spotify_user_id: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(200))
    refresh_token: Mapped[str] = mapped_column(String(1000))
    access_token: Mapped[str | None] = mapped_column(String(1000))
    # Seconds since the epoch, so time zones never come into it.
    access_expires_at: Mapped[float] = mapped_column(default=0.0)
    connected_at: Mapped[float]
