export type Role = "user" | "curator" | "admin";

export type Permission =
  | "add_tracks"
  | "vote"
  | "remove_own_tracks"
  | "manage_queue"
  | "manage_playlists"
  | "create_stations"
  | "plan_lineups"
  | "switch_source"
  | "transport"
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
  /** Their photo, if they've added one. */
  avatar_url: string | null;
};

/** Someone, as shown beside their requests. */
export type Person = { id: number; display_name: string; avatar_url: string | null };

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
    /** Whether the speakers are playing it, even while GuildFM itself is stopped. */
    playing: boolean;
  } | null;
  /** What Previous does now, or null when it's unavailable (greyed out). */
  previous: "back" | "restart" | null;
  /** An announcement is playing. */
  announcing: boolean;
  /** The station's DJ is talking. */
  dj_talking: boolean;
  /** A station is playing a jingle. */
  jingle: boolean;
  group_volume: number | null;
  rooms: Room[];
  /** Whether playback hours are open now, and when that next changes. */
  hours: { open: boolean; next_change: string | null } | null;
  /** Monitor mode: GuildFM plays in browsers instead of on the speakers. */
  monitor: boolean;
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

/** Asks the API for audio, such as a voice preview, and returns it as a Blob. */
export async function apiAudio(path: string, body: unknown): Promise<Blob> {
  const response = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new ApiError(response.status, errorMessage(data));
  }
  return response.blob();
}

/** Sends a file, such as a photo, as the request body, and returns the JSON answer. */
export async function apiUpload<T>(path: string, file: Blob, method: "PUT" | "POST" = "PUT"): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
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

export type SearchAlbum = {
  id: string;
  name: string;
  artists: string;
  art_url: string | null;
  year: string | null;
  kind: "album" | "single" | "compilation";
  /** How many songs Spotify lists on it. */
  tracks: number;
};

/** An album's songs in order, leaving out any that can't play here or aren't allowed. */
export type AlbumDetail = SearchAlbum & { items: SearchTrack[] };

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
  /** Null for songs from the playlist or station. */
  requested_by: Person | null;
  /** The playlist a song came from, if it did. */
  playlist: string | null;
  /** The station a song came from, if it did. */
  station: string | null;
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
  /** The album's name, for a song a curator or admin queued with the rest of its album. */
  album: string | null;
};

/** A whole album queued by a curator or admin, and how many of its songs went in. */
export type AlbumQueued = { queue: QueueState; added: number };

export type QueueSource = {
  kind: "playlist" | "station";
  id: number;
  name: string;
  upcoming: { track: SearchTrack; down: number; my_down: boolean }[];
  /** Thumbs down needed to skip one of the upcoming songs. */
  skip_at: number;
};

export type QueueState = {
  playing: QueueEntry | null;
  next: QueueEntry | null;
  waiting: QueueEntry[];
  /** The playlist or station filling the gaps between requests. */
  source: QueueSource | null;
  activity: { text: string; at: string }[];
  mine: number;
  request_cap: number;
};

export type SearchResult = {
  tracks: FoundTrack[];
  artists: SearchArtist[];
  /** Only when adding to a playlist, on the first page. */
  albums: SearchAlbum[];
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

export type Hours = { on: boolean; start: string; end: string };

export type SettingsValues = {
  allow_explicit: boolean;
  request_cap: number;
  downvote_threshold: number;
  recently_played_hours: number;
  best_voted_min_upvotes: number;
  best_voted_size: number;
  queue_runs_out: "restart_playlist" | "default_station" | "ai_pick";
  /** A station id, for queue_runs_out "default_station". */
  default_station: number | null;
  schedule: Record<"mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun", Hours>;
  timezone: string;
  weather_location: string;
  announcement_voice: string;
  /** What GuildFM is, for the AI writing system idents. */
  about: string;
};

export type SettingsState = {
  values: SettingsValues;
  timezones: string[];
  hours: { open: boolean; next_change: string | null };
  /** For the default station. AI picks is the fallback anyway, so it isn't listed. */
  stations: { id: number; name: string }[];
};

export type Playlist = {
  id: number;
  name: string;
  kind: "custom" | "imported" | "best_voted";
  shuffle: boolean;
  tracks: number;
  /** Album art from its first few songs. */
  covers: string[];
  made_by: string | null;
  playing: boolean;
};

/** A playlist as a source on the Now Playing screen. */
export type PlaylistTile = {
  id: number;
  name: string;
  kind: Playlist["kind"];
  tracks: number;
  shuffle: boolean;
  /** Album art from its first few songs. */
  covers: string[];
  last_played_at: string | null;
  /** The playlist filling the gaps between requests. */
  filling: boolean;
  /** The current song came from it. */
  on_air: boolean;
  /** The line-up that's on is playing it. */
  in_lineup: boolean;
};

/** A DJ, who can host any number of stations. */
export type DJProfile = {
  id: number;
  name: string;
  personality: string;
  voice: string;
  /** The stations they host, by name. */
  stations: { id: number; name: string }[];
};

export type SourceKind = "queue" | "library" | "radio" | "lineups";

/** A station as a source on the Now Playing screen. */
export type StationTile = {
  id: number;
  name: string;
  kind: StationKind;
  description: string;
  /** Null without a DJ. */
  dj_name: string | null;
  global_awareness: boolean;
  /** Its cover, once OpenAI has painted one. */
  art_url: string | null;
  last_played_at: string | null;
  /** The station filling the gaps between requests. */
  filling: boolean;
  /** The current song came from it. */
  on_air: boolean;
  /** The line-up that's on is playing it. */
  in_lineup: boolean;
};

/** A stretch of a line-up's day, in minutes after midnight: a show or a playlist. */
export type LineupSlot = {
  start: number;
  end: number;
  kind: "show" | "playlist";
  station_id: number | null;
  playlist_id: number | null;
  name: string;
  /** The station's cover, or the playlist's first album cover. */
  art_url: string | null;
  /** A show's DJ, null without one. */
  dj_name: string | null;
  /** A playlist's own length, in minutes. */
  minutes: number | null;
};

/** The day line-ups plan: the earliest opening and latest closing in the playback hours. */
export type LineupDay = { start: number; end: number };

/** A line-up as a source on the Now Playing screen. */
export type LineupTile = {
  id: number;
  name: string;
  art_url: string | null;
  slots: LineupSlot[];
  last_on_at: string | null;
  /** It's the source now. */
  on: boolean;
};

export type Lineup = LineupTile & { description: string; made_by: string | null };

/** What the line-up editor offers: the day, and the shows and playlists to put on it. */
export type LineupChoices = {
  day: LineupDay;
  shows: { id: number; name: string; art_url: string | null; dj_name: string | null }[];
  playlists: { id: number; name: string; covers: string[]; minutes: number }[];
};

export type NowState = {
  /** Where the current song came from, if GuildFM put it on. */
  on_air: SourceKind | null;
  /** Someone chose to have nothing fill the gaps between requests. */
  requests_only: boolean;
  /** Last played first. */
  playlists: PlaylistTile[];
  /** Last played first. */
  stations: StationTile[];
  /** The one on first, then the most recently on. */
  lineups: LineupTile[];
  day: LineupDay;
  /** The time in the office when this was sent, in minutes after midnight. */
  minute: number;
  /** What fills a gap in a line-up. */
  gap: string;
};

export type Play = {
  id: number;
  track: SearchTrack;
  played_at: string;
  requested_by: Person | null;
  playlist: string | null;
  station: string | null;
  upvotes: number;
  downvotes: number;
};

export type History = {
  /** Newest first. */
  plays: Play[];
  /** Earlier plays today, fetched with ?before=<the last play's id>. */
  more: boolean;
};

export type PlaylistDetail = Playlist & {
  items: (SearchTrack & { position: number; upvotes: number })[];
};

export type Day = keyof SettingsValues["schedule"];

export type RoomRef = { uid: string; name: string };

export type AnnounceMode = "over" | "after";

export type Repeat = "once" | "daily" | "weekdays" | "days" | "hourly";

export type Announcement = {
  id: number;
  text: string;
  /** Null for every room. */
  rooms: RoomRef[] | null;
  mode: AnnounceMode;
  start_date: string;
  /** "13:55", in the office's time zone. */
  at: string;
  repeat: Repeat;
  days: Day[];
  ends_on: string | null;
  active: boolean;
  /** When it next plays (if it's on), or null when it never will. */
  next_at: string | null;
  /** Whether that's inside playback hours. */
  in_hours: boolean;
};

export type AnnouncementLog = {
  id: number;
  text: string;
  /** Room names, or null for every room. */
  rooms: string[] | null;
  played_at: string;
  /** Why it didn't play, if it didn't. */
  problem: string | null;
};

export type AnnouncementsState = {
  /** Soonest first, then any that are off. */
  scheduled: Announcement[];
  /** Newest first. */
  recent: AnnouncementLog[];
  /** The announcement voice from settings. */
  voice: string;
};

export type StationKind = "custom" | "ai_picks";

/** OpenAI's voices, as in prefs.py, for while the full list loads. Marin and Cedar sound the
 * most natural. */
export const VOICES = [
  "marin", "cedar", "alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage",
  "shimmer", "verse",
] as const;

export type StationFields = {
  name: string;
  description: string;
  global_awareness: boolean;
  dj: boolean;
  /** The DJ the name, personality and voice are for; null for a new one. */
  dj_id: number | null;
  dj_name: string;
  personality: string;
  voice: string;
  talk_every: number;
  talk_unit: "tracks" | "minutes";
  style: "announce" | "commentary";
  announce_requests: boolean;
  /** Plays idents between songs. */
  jingles: boolean;
  /** The speakers fade each song into the next while it's on. */
  crossfade: boolean;
};

export type Station = StationFields & {
  id: number;
  kind: StationKind;
  /** Its cover, once OpenAI has painted one. */
  art_url: string | null;
  made_by: string | null;
  /** The station filling the gaps between requests. */
  playing: boolean;
  last_played_at: string | null;
};

/** A song in a station's previewed hour, with the jingle and what the DJ says before it. */
export type HourSlot = {
  track: SearchTrack;
  /** Why the AI picked it. */
  note: string;
  starts_at: string;
  line: string | null;
  /** Played in the pause before this song. */
  jingle: Jingle | null;
};

export type Hour = { slots: HourSlot[]; minutes: number };

/** A short ident played between songs: GuildFM's own (system), or one station's (station). */
export type Jingle = {
  id: number;
  kind: "system" | "station";
  station_id: number | null;
  name: string;
  seconds: number;
  /** For the browser to play. */
  url: string;
};

/** A jingle description the AI wrote for the jingle generator. */
export type JingleIdea = {
  name: string;
  prompt: string;
  seconds: number;
};

/** A station as its editor has it, saved or not, for the AI writing its station idents. */
export type StationAsEdited = {
  name: string;
  description: string;
  dj_name: string;
  personality: string;
};

export type DraftStatus = "making" | "ready" | "failed" | "kept" | "turned_down";

/** A jingle ElevenLabs is making or has made in the generator, to keep or turn down. */
export type JingleDraft = {
  id: number;
  station_id: number | null;
  name: string;
  prompt: string;
  /** The seconds asked for. */
  length: number;
  instrumental: boolean;
  status: DraftStatus;
  /** How long it plays, once made. */
  seconds: number | null;
  /** For the browser to play, once made. */
  url: string | null;
  /** Why ElevenLabs couldn't make it. */
  problem: string | null;
  /** ElevenLabs' own wording, when it refused the description. */
  suggestion: string | null;
};

/** The generator's round, and how many made before were kept and turned down. */
export type JingleRound = {
  drafts: JingleDraft[];
  kept: number;
  turned_down: number;
};

/** The voices GuildFM can speak in. An ElevenLabs voice's id starts "elevenlabs:". */
export type Voices = {
  openai: string[];
  elevenlabs: { id: string; name: string }[];
  /** Whether there's an ElevenLabs key in .env. */
  elevenlabs_ready: boolean;
};

/** How an outside service is doing. "off" isn't set up; "unused" hasn't been needed yet. */
export type ServiceState = "ok" | "failing" | "unused" | "off";

export type Service = {
  key: string;
  name: string;
  state: ServiceState;
  /** What it's for, or what's wrong. */
  detail: string;
  ok_at: string | null;
  failed_at: string | null;
};

/** The admins' status page: the speakers, outside services, backups and recent problems. */
export type SystemStatus = {
  version: string;
  started_at: string;
  /** Browsers with GuildFM open. */
  connected: number;
  services: Service[];
  /** ElevenLabs credits this month, when it'll say. */
  credits: { used: number; limit: number; resets_at: string | null } | null;
  backups: { folder: string; count: number; latest_at: string | null };
  /** Bytes free where the data folder is. */
  disk_free: number;
  problems: {
    at: string;
    level: "warning" | "error";
    source: string;
    message: string;
    count: number;
  }[];
};
