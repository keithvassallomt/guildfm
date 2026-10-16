import { useCallback, useEffect, useRef, useState } from "react";
import { apiAudio, errorText } from "../api";
import { Button } from "./Button";
import { Icon } from "./Icon";
import styles from "./PreviewButton.module.css";

type Status = "idle" | "loading" | "playing";

/** Reads text out in this browser, never on the office speakers. */
export function usePreview() {
  const [status, setStatus] = useState<Status>("idle");
  const audio = useRef<HTMLAudioElement | null>(null);
  const url = useRef<string | null>(null);
  // Bumped by every play and stop, so a preview that's still loading knows it's been dropped.
  const latest = useRef(0);

  const stop = useCallback(() => {
    latest.current += 1;
    audio.current?.pause();
    audio.current = null;
    if (url.current) URL.revokeObjectURL(url.current);
    url.current = null;
    setStatus("idle");
  }, []);

  useEffect(() => stop, [stop]);

  const play = useCallback(
    async (path: string, body: Record<string, unknown>) => {
      stop();
      const mine = latest.current;
      setStatus("loading");
      try {
        const blob = await apiAudio(path, body);
        if (mine !== latest.current) return;
        url.current = URL.createObjectURL(blob);
        audio.current = new Audio(url.current);
        audio.current.onended = stop;
        setStatus("playing");
        await audio.current.play();
      } catch (error) {
        if (mine === latest.current) stop();
        throw error;
      }
    },
    [stop],
  );

  return { status, play, stop };
}

type Props = {
  text: string;
  onError: (message: string | null) => void;
  /** Which voice to hear: an announcement (the default) or a station's DJ. */
  endpoint?: string;
  /** More for the preview, such as the voice. The announcement voice when left out. */
  extra?: Record<string, unknown>;
};

/** Plays `text` in the browser, or stops it. OpenAI takes a moment the first time. */
export function PreviewButton({ text, onError, endpoint = "/announcements/preview", extra }: Props) {
  const { status, play, stop } = usePreview();
  const words = text.trim();

  const press = () => {
    if (status !== "idle") {
      stop();
      return;
    }
    onError(null);
    play(endpoint, { ...extra, text: words }).catch((error) => onError(errorText(error)));
  };

  return (
    <Button
      variant="secondary"
      className={`${styles.button} ${status !== "idle" ? styles.busy : ""}`}
      disabled={!words}
      onClick={press}
    >
      <Icon name={status === "playing" ? "stop" : "play"} size={14} />
      {status === "loading" ? "Getting it ready..." : status === "playing" ? "Stop" : "Preview"}
    </Button>
  );
}
