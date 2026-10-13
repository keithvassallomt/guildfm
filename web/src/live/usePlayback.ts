import { useCallback, useEffect, useState } from "react";
import { api, type PlaybackState } from "../api";
import { useLiveEvent } from "./LiveProvider";

/** What's on the speakers, kept up to date by the server's live broadcasts. */
export function usePlayback() {
  const [state, setState] = useState<PlaybackState | null>(null);
  const [receivedAt, setReceivedAt] = useState(() => Date.now());

  const apply = useCallback((next: PlaybackState) => {
    setState(next);
    setReceivedAt(Date.now());
  }, []);

  useEffect(() => {
    api<PlaybackState>("GET", "/playback")
      .then(apply)
      .catch(() => {});
  }, [apply]);

  useLiveEvent("playback", (data) => apply(data as PlaybackState));

  return { state, receivedAt, apply };
}

/** The play position, ticking along between updates from the server. */
export function usePosition(state: PlaybackState | null, receivedAt: number): number {
  const [now, setNow] = useState(() => Date.now());
  const playing = state?.status === "playing";

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [playing]);

  const track = state?.track;
  if (!track) return 0;
  const elapsed = playing ? Math.max(0, (now - receivedAt) / 1000) : 0;
  return track.duration ? Math.min(track.duration, track.position + elapsed) : track.position;
}

export function clock(seconds: number): string {
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
