from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

AVATARS = "avatars"  # the folder for people's photos, inside the media folder
JINGLES = "jingles"  # the folder for jingles, inside the media folder
COVERS = "covers"  # the folder for stations' covers, inside the media folder


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
    # Their photo's file name in the media folder's avatars, if they've added one.
    avatar: Mapped[str | None] = mapped_column(String(64), default=None)
    must_change_password: Mapped[bool] = mapped_column(default=False)
    # Part of every session cookie. Bumping it signs the user out everywhere.
    session_version: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def avatar_url(self) -> str | None:
        return f"/media/{AVATARS}/{self.avatar}" if self.avatar else None


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


class EntryState(StrEnum):
    WAITING = "waiting"  # in the vote
    NEXT = "next"  # already handed to the speakers, so locked in place
    PLAYING = "playing"


class PlaylistKind(StrEnum):
    CUSTOM = "custom"  # made in GuildFM
    IMPORTED = "imported"  # copied from a Spotify playlist
    BEST_VOTED = "best_voted"  # the one GuildFM keeps itself


class Playlist(Base):
    __tablename__ = "playlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[PlaylistKind] = mapped_column(
        Enum(PlaylistKind, native_enum=False, length=16, values_callable=enum_values)
    )
    # The Spotify playlist or album it was imported from.
    spotify_id: Mapped[str | None] = mapped_column(String(64), default=None)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[float]
    shuffle: Mapped[bool] = mapped_column(default=False)
    # Where it left off when something else was put on: its order, cursor, skipped songs and
    # thumbs down, as in SourceState. Putting it back on carries on from there.
    resume: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)

    creator: Mapped[User | None] = relationship(lazy="joined")


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"

    playlist_id: Mapped[int] = mapped_column(
        ForeignKey("playlists.id", ondelete="CASCADE"), primary_key=True
    )
    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id"), primary_key=True)
    position: Mapped[int]
    added_at: Mapped[float]
    # For Best Voted: the most upvotes the track has had as a request.
    upvotes: Mapped[int] = mapped_column(default=0)

    track: Mapped[Track] = relationship(lazy="joined")


class StationKind(StrEnum):
    CUSTOM = "custom"
    AI_PICKS = "ai_picks"  # the one GuildFM keeps itself: songs that fit what's been playing


class TalkUnit(StrEnum):
    TRACKS = "tracks"
    MINUTES = "minutes"


class DJStyle(StrEnum):
    ANNOUNCE = "announce"  # what was playing and what's next
    COMMENTARY = "commentary"  # trivia, the weather, the odd story


class JingleKind(StrEnum):
    SYSTEM = "system"  # GuildFM's own, for any AI station
    STATION = "station"  # one station's own


class DJProfile(Base):
    """A DJ, who can host any number of AI stations: who they are and how they sound. How often
    they talk on a station, and about what, is up to the station. Kept when no station has them,
    so they can host another."""

    __tablename__ = "djs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    personality: Mapped[str] = mapped_column(String(600), default="")
    # An OpenAI voice ("marin"), or an ElevenLabs one ("elevenlabs:" and its id).
    voice: Mapped[str] = mapped_column(String(64), default="marin")
    created_at: Mapped[float]


class Station(Base):
    """An AI radio station: the AI picks its songs from a description, and an optional DJ talks
    between them."""

    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[StationKind] = mapped_column(
        Enum(StationKind, native_enum=False, length=16, values_callable=enum_values),
        default=StationKind.CUSTOM,
    )
    description: Mapped[str] = mapped_column(String(600))
    global_awareness: Mapped[bool] = mapped_column(default=False)
    # The DJ hosting it, if any. A DJ can host several stations.
    dj_id: Mapped[int | None] = mapped_column(
        ForeignKey("djs.id", ondelete="SET NULL"), default=None
    )
    talk_every: Mapped[int] = mapped_column(default=3)
    talk_unit: Mapped[TalkUnit] = mapped_column(
        Enum(TalkUnit, native_enum=False, length=16, values_callable=enum_values),
        default=TalkUnit.TRACKS,
    )
    style: Mapped[DJStyle] = mapped_column(
        Enum(DJStyle, native_enum=False, length=16, values_callable=enum_values),
        default=DJStyle.COMMENTARY,
    )
    announce_requests: Mapped[bool] = mapped_column(default=True)
    jingles: Mapped[bool] = mapped_column(default=True)  # plays idents between songs
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[float]
    # Track ids it picked lately, oldest first, so it doesn't repeat itself.
    picked: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Its cover's file name in the media folder's covers, once OpenAI has painted one.
    art: Mapped[str | None] = mapped_column(String(64), default=None)
    # The name and description the cover was painted from, as covers.painted_from has them.
    art_for: Mapped[str | None] = mapped_column(String(32), default=None)

    creator: Mapped[User | None] = relationship(lazy="joined")
    host: Mapped[DJProfile | None] = relationship(lazy="joined")

    # The DJ's details, as the DJ, the hour preview and the editor's form all see them.
    @property
    def dj(self) -> bool:
        return self.host is not None

    @property
    def dj_name(self) -> str:
        return self.host.name if self.host else ""

    @property
    def personality(self) -> str:
        return self.host.personality if self.host else ""

    @property
    def voice(self) -> str:
        return self.host.voice if self.host else "marin"

    @property
    def art_url(self) -> str | None:
        return f"/media/{COVERS}/{self.art}" if self.art else None


class Jingle(Base):
    """A short ident played between songs on AI stations: a system ident, GuildFM's own, or a
    station ident, one station's. Deleting the station deletes its jingles."""

    __tablename__ = "jingles"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[JingleKind] = mapped_column(
        Enum(JingleKind, native_enum=False, length=16, values_callable=enum_values)
    )
    # The station a station ident belongs to; None for a system ident.
    station_id: Mapped[int | None] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), default=None
    )
    name: Mapped[str] = mapped_column(String(100))
    file: Mapped[str] = mapped_column(String(64))  # its file name in the media folder's jingles
    seconds: Mapped[float]
    created_at: Mapped[float]

    @property
    def url(self) -> str:
        return f"/media/{JINGLES}/{self.file}"


class SourceState(Base):
    """What fills the gaps between requests: a playlist and how far through it GuildFM is, or a
    station and the songs it has picked so far. A row with neither means "requests only" was
    chosen; no row at all means nothing was, so the "when the queue runs out" setting decides.
    There's at most one row, with id 1."""

    __tablename__ = "playback_source"

    id: Mapped[int] = mapped_column(primary_key=True)
    playlist_id: Mapped[int | None] = mapped_column(
        ForeignKey("playlists.id", ondelete="CASCADE"), default=None
    )
    station_id: Mapped[int | None] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), default=None
    )
    # This time round's order of track ids: shuffled, or as listed. For a station, its picks.
    order: Mapped[list[str]] = mapped_column(JSON, default=list)
    cursor: Mapped[int] = mapped_column(default=0)
    # Tracks thumbed down enough to skip this time round, and who thumbed them down.
    skipped: Mapped[list[str]] = mapped_column(JSON, default=list)
    downvotes: Mapped[dict[str, list[int]]] = mapped_column(JSON, default=dict)
    # For a station with a DJ: songs since the DJ last talked, when that was, and where it
    # talked and what it said lately. None until it's first asked, each time the station comes on.
    dj_memory: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)

    playlist: Mapped[Playlist | None] = relationship(lazy="joined")
    station: Mapped[Station | None] = relationship(lazy="joined")


class QueueEntry(Base):
    """A song in the queue: someone's request, or the next from the playing playlist.
    Deleting the requester deletes their requests."""

    __tablename__ = "queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Unique: a song can only be in the queue once.
    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id"), unique=True)
    # None for songs from the playing playlist.
    requested_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), default=None
    )
    playlist_id: Mapped[int | None] = mapped_column(
        ForeignKey("playlists.id", ondelete="SET NULL"), default=None
    )
    station_id: Mapped[int | None] = mapped_column(
        ForeignKey("stations.id", ondelete="SET NULL"), default=None
    )
    added_at: Mapped[float]
    state: Mapped[EntryState] = mapped_column(
        Enum(EntryState, native_enum=False, length=16, values_callable=enum_values),
        default=EntryState.WAITING,
    )
    # Set when a curator moves the entry; from then on votes don't move it.
    pinned_position: Mapped[int | None] = mapped_column(default=None)
    # The Spotify album, for a song a curator or admin queued with the rest of its album. Those
    # don't count towards their request cap.
    album_id: Mapped[str | None] = mapped_column(String(22), default=None)

    track: Mapped[Track] = relationship(lazy="joined")
    requester: Mapped[User | None] = relationship(lazy="joined")
    playlist: Mapped[Playlist | None] = relationship(lazy="joined")
    station: Mapped[Station | None] = relationship(lazy="joined")


class Vote(Base):
    """One person's thumbs up (+1) or down (-1) on a request."""

    __tablename__ = "votes"

    entry_id: Mapped[int] = mapped_column(
        ForeignKey("queue.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    value: Mapped[int]


class Play(Base):
    """A track GuildFM played, kept for the play history, "recently played" and Best Voted."""

    __tablename__ = "plays"

    id: Mapped[int] = mapped_column(primary_key=True)
    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id"), index=True)
    requested_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    # The playlist or station it came from, when it wasn't a request.
    playlist_id: Mapped[int | None] = mapped_column(
        ForeignKey("playlists.id", ondelete="SET NULL"), default=None, index=True
    )
    station_id: Mapped[int | None] = mapped_column(
        ForeignKey("stations.id", ondelete="SET NULL"), default=None, index=True
    )
    played_at: Mapped[float] = mapped_column(index=True)
    upvotes: Mapped[int] = mapped_column(default=0)
    downvotes: Mapped[int] = mapped_column(default=0)

    track: Mapped[Track] = relationship(lazy="joined")
    requester: Mapped[User | None] = relationship(lazy="joined")
    playlist: Mapped[Playlist | None] = relationship(lazy="joined")
    station: Mapped[Station | None] = relationship(lazy="joined")


class PickNote(Base):
    """Why the AI picked a song for a station, for the DJ to mention, and the kind of jingle it
    wants before it, if any. Kept for the newest few hundred picks."""

    __tablename__ = "pick_notes"

    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id"), primary_key=True)
    note: Mapped[str] = mapped_column(String(500))
    ident: Mapped[str | None] = mapped_column(String(16), default=None)  # "system" or "station"
    picked_at: Mapped[float] = mapped_column(index=True)


class AnnounceMode(StrEnum):
    OVER = "over"  # over the music, which goes quiet and comes back up
    AFTER = "after"  # between songs, once the current one finishes


class Repeat(StrEnum):
    ONCE = "once"
    DAILY = "daily"
    WEEKDAYS = "weekdays"
    DAYS = "days"  # the chosen days of the week
    HOURLY = "hourly"  # every hour, at the same minutes past, in playback hours


class Announcement(Base):
    """An announcement an admin scheduled, once or on repeat. One played straight away isn't
    kept here, only in the log of what played."""

    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(String(600))
    # The rooms it plays in, as [{"uid": ..., "name": ...}], or None for every room.
    rooms: Mapped[list[dict[str, str]] | None] = mapped_column(JSON, default=None)
    mode: Mapped[AnnounceMode] = mapped_column(
        Enum(AnnounceMode, native_enum=False, length=16, values_callable=enum_values)
    )
    # When it first plays, in the office's time zone.
    start_date: Mapped[date]
    at: Mapped[str] = mapped_column(String(5))  # "13:55"
    repeat: Mapped[Repeat] = mapped_column(
        Enum(Repeat, native_enum=False, length=16, values_callable=enum_values)
    )
    days: Mapped[list[str]] = mapped_column(JSON, default=list)  # "mon" to "sun", for DAYS
    ends_on: Mapped[date | None] = mapped_column(default=None)  # the last day it plays
    active: Mapped[bool] = mapped_column(default=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[float]
    # Times up to this one, in seconds since the epoch, have been dealt with: played, or let go.
    handled_until: Mapped[float]


class AnnouncementPlay(Base):
    """An announcement that played, or was due and didn't, for "Recently played"."""

    __tablename__ = "announcement_plays"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(String(600))
    rooms: Mapped[list[str] | None] = mapped_column(JSON, default=None)  # names; None is all
    played_at: Mapped[float] = mapped_column(index=True)
    problem: Mapped[str | None] = mapped_column(String(300), default=None)  # why it didn't play
