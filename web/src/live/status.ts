import type { PlaybackStatus } from "../api";

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
