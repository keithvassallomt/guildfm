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

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type Method = "GET" | "POST" | "PATCH" | "DELETE";

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
