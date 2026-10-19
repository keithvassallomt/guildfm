import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorText } from "../api";
import { useLiveEvent } from "../live/LiveProvider";
import { MonitorAudio, type MonitorState } from "../live/monitorAudio";
import { usePlayback } from "../live/usePlayback";
import { Button } from "./Button";
import { Icon } from "./Icon";
import styles from "./MonitorBar.module.css";

/** For admins while monitor mode is on: GuildFM plays in browsers instead of on the speakers,
 * and this is where a browser starts listening. */
export function MonitorBar() {
  const { state } = usePlayback();
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const engine = useRef<MonitorAudio | null>(null);
  const on = state?.monitor ?? false;

  useLiveEvent("monitor", (data) => engine.current?.apply(data as MonitorState));

  const stop = useCallback(() => {
    engine.current?.close();
    engine.current = null;
    setListening(false);
  }, []);

  // Silent once monitor mode goes off, and when the app closes.
  useEffect(() => {
    if (!on) stop();
  }, [on, stop]);
  useEffect(() => stop, [stop]);

  const listen = async () => {
    setError(null);
    const audio = new MonitorAudio();
    engine.current = audio;
    setListening(true);
    try {
      audio.apply(await api<MonitorState>("GET", "/playback/monitor"));
    } catch (caught) {
      setError(errorText(caught));
    }
  };

  if (!on) return null;
  return (
    <section className={styles.bar} aria-label="Monitor mode">
      <Icon name="headphones" />
      <span className={styles.text}>
        <strong>Monitor mode</strong>
        <span>
          {error ??
            (listening
              ? "Playing in this browser: beeps for songs, and the DJ, jingles and announcements for real."
              : "GuildFM plays in browsers, not on the speakers.")}
        </span>
      </span>
      {listening ? (
        <Button variant="secondary" onClick={stop}>
          Stop listening
        </Button>
      ) : (
        <Button onClick={listen}>Listen here</Button>
      )}
    </section>
  );
}
