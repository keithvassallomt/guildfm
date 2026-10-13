"""Who can do what. Mirrors the permissions table in stream.md."""

from enum import StrEnum

from guildfm.models import Role


class Permission(StrEnum):
    ADD_TRACKS = "add_tracks"
    VOTE = "vote"
    REMOVE_OWN_TRACKS = "remove_own_tracks"
    MANAGE_QUEUE = "manage_queue"  # remove any track, reorder, override votes
    MANAGE_PLAYLISTS = "manage_playlists"  # create and import
    CREATE_STATIONS = "create_stations"
    SWITCH_SOURCE = "switch_source"  # start or switch playlists and AI stations
    CONTROL_PLAYBACK = "control_playback"  # play, pause, resume, skip, volume, stop
    ANNOUNCE = "announce"
    MANAGE_USERS = "manage_users"  # create accounts, reset passwords, change roles
    CHANGE_SETTINGS = "change_settings"


_EVERYONE = {Permission.ADD_TRACKS, Permission.VOTE, Permission.REMOVE_OWN_TRACKS}
_CURATORS = _EVERYONE | {
    Permission.MANAGE_QUEUE,
    Permission.MANAGE_PLAYLISTS,
    Permission.CREATE_STATIONS,
    Permission.SWITCH_SOURCE,
}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.USER: frozenset(_EVERYONE),
    Role.CURATOR: frozenset(_CURATORS),
    Role.ADMIN: frozenset(Permission),
}


def can(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
