export type Role = "user" | "curator" | "admin";

export type Permission =
  | "add_tracks"
  | "vote"
  | "remove_own_tracks"
  | "manage_queue"
  | "manage_playlists"
  | "create_stations"
  | "switch_source"
  | "control_playback"
  | "announce"
  | "manage_users"
  | "change_settings";

export type User = {
  id: number;
  username: string;
  display_name: string;
  role: Role;
  announce_requests: boolean;
  must_change_password: boolean;
};

export type Me = User & { permissions: Permission[] };

export type TemporaryPassword = { user: User; temporary_password: string };

export type PlaybackStatus = "offline" | "stopped" | "playing" | "paused" | "idle" | "overridden";

export type Room = {
  uid: string;
  name: string;
  model: string;
  volume: number;
  in_group: boolean;
  on_tv: boolean;
};

export type PlaybackState = {
  status: PlaybackStatus;
  error: string | null;
  coordinator: string | null;
  track: {
    title: string;
    artist: string;
    album: string;
    art_url: string | null;
    duration: number;
    position: number;
    /** Whether GuildFM put this track on, rather than someone else. */
    ours: boolean;
  } | null;
  group_volume: number | null;
  rooms: Room[];
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

/** Calls the GuildFM API and returns its JSON, or throws an ApiError with a readable message. */
export async function api<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, errorMessage(data));
  return data as T;
}

function errorMessage(data: unknown): string {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((error: { msg?: string }) => error.msg).join(" ");
  }
  return "Something went wrong. Try again.";
}

/** A message to show the person when an API call fails. */
export function errorText(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "Couldn't reach GuildFM. Check you're on the office network.";
}

export type SearchTrack = {
  id: string;
  title: string;
  artists: string;
  album: string;
  duration: number;
  explicit: boolean;
  art_url: string | null;
};

export type SearchArtist = { id: string; name: string; art_url: string | null };

export type FoundTrack = SearchTrack & {
  /** Already in the queue, so it can't be requested again. */
  queued: boolean;
  /** When it last played, if recently. */
  played_at: string | null;
};

export type QueueEntry = {
  id: number;
  state: "waiting" | "next" | "playing";
  track: SearchTrack;
  requested_by: { id: number; display_name: string };
  requested_at: string;
  up: number;
  down: number;
  score: number;
  my_vote: -1 | 0 | 1;
  mine: boolean;
  /** Placed by a curator, so votes don't move it. */
  pinned: boolean;
  /** When it last played before this request, if recently. */
  played_at: string | null;
};

export type QueueState = {
  playing: QueueEntry | null;
  next: QueueEntry | null;
  waiting: QueueEntry[];
  activity: { text: string; at: string }[];
  mine: number;
  request_cap: number;
};

export type SearchResult = {
  tracks: FoundTrack[];
  artists: SearchArtist[];
  next_offset: number | null;
};

export type SpotifyAccount = {
  connected: boolean;
  display_name: string | null;
  connected_at: string | null;
  reconnect_by: string | null;
  reconnect_soon: boolean;
  playlists: number | null;
  problem: string | null;
};
