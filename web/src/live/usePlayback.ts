import { useCallback, useEffect, useState } from "react";
import { api, type PlaybackState } from "../api";
import { useLiveEvent } from "./LiveProvider";

/** What's on the speakers, kept up to date by the server's live broadcasts. */
export function usePlayback() {
  const [state, setState] = useState<PlaybackState | null>(null);
  // When the latest state arrived, so the play position can tick along from it.
  const [receivedAt, setReceivedAt] = useState(() => performance.now());

  const apply = useCallback((next: PlaybackState) => {
    setState(next);
    setReceivedAt(performance.now());
  }, []);

  useEffect(() => {
    api<PlaybackState>("GET", "/playback")
      .then(apply)
      .catch(() => {});
  }, [apply]);

  useLiveEvent("playback", (data) => apply(data as PlaybackState));

  return { state, receivedAt, apply };
}

export function clock(seconds: number): string {
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
