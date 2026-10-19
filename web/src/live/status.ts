import type { PlaybackState, PlaybackStatus, QueueEntry } from "../api";

export const statusLabels: Record<PlaybackStatus, string> = {
  playing: "On air",
  paused: "Paused",
  idle: "Nothing playing",
  stopped: "Stopped",
  overridden: "Overridden",
  offline: "Speakers offline",
};

export const statusTones: Record<PlaybackStatus, "live" | "idle" | "warn"> = {
  playing: "live",
  paused: "idle",
  idle: "idle",
  stopped: "idle",
  overridden: "warn",
  offline: "warn",
};

/** "just now", "12 min ago", "3h ago", "yesterday". */
export function ago(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return hours < 48 ? "yesterday" : `${Math.round(hours / 24)} days ago`;
}

/** "Opens again Wednesday at 08:00." or "No playback hours are set." */
export function opensAgain(hours: { next_change: string | null }): string {
  if (!hours.next_change) return "No playback hours are set.";
  const when = new Date(hours.next_change);
  const day = when.toLocaleDateString(undefined, { weekday: "long" });
  const time = when.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const today = new Date().toDateString() === when.toDateString();
  return `Opens again ${today ? "today" : day} at ${time}.`;
}

/** Whether GuildFM's own sound is on: an announcement, the DJ or a jingle. */
export function ownClip(state: PlaybackState): boolean {
  return state.announcing || state.dj_talking || state.jingle;
}

/** The status chip's words: "Closed" rather than "Stopped" outside playback hours. */
export function chipLabel(state: PlaybackState): string {
  if (state.announcing) return "Announcing";
  if (state.dj_talking) return "DJ talking";
  if (state.jingle) return "Jingle";
  if (state.status === "stopped" && state.hours?.open === false) return "Closed";
  return statusLabels[state.status];
}

/** Who a queued song is from: "Requested by Priya", "Requested by you", or "From Fridays". */
export function credit(entry: QueueEntry): string {
  if (entry.requested_by) {
    const who = entry.mine ? "you" : entry.requested_by.display_name;
    return `Requested by ${who}${entry.album ? " · whole album" : ""}`;
  }
  if (entry.station) return `On ${entry.station}`;
  return entry.playlist ? `From ${entry.playlist}` : "From a playlist";
}
