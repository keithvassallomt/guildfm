import { useCallback, useEffect, useId, useRef, useState } from "react";
import { api, errorText } from "../api";
import { useLiveEvent } from "../live/LiveProvider";
import { MonitorAudio, type MonitorState } from "../live/monitorAudio";
import { usePlayback } from "../live/usePlayback";
import { Button } from "./Button";
import { Icon } from "./Icon";
import styles from "./MonitorBar.module.css";
import { Toggle } from "./Toggle";

/** For admins while monitor mode is on: GuildFM plays in browsers instead of on the speakers,
 * and this is where a browser starts listening. */
export function MonitorBar() {
  const { state } = usePlayback();
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const engine = useRef<MonitorAudio | null>(null);
  const on = state?.monitor ?? false;
  // Songs only play until the DJ's next words are ready, so testing isn't minutes of beeps.
  const [skip, setSkip] = useState(false);
  const skipId = useId();

  useLiveEvent("monitor", (data) => {
    const monitor = data as MonitorState;
    setSkip(monitor.skip_music);
    engine.current?.apply(monitor);
  });

  useEffect(() => {
    if (!on) return;
    api<MonitorState>("GET", "/playback/monitor")
      .then((monitor) => setSkip(monitor.skip_music))
      .catch(() => {});
  }, [on]);

  const skipMusic = async (next: boolean) => {
    setError(null);
    setSkip(next);
    try {
      const monitor = await api<MonitorState>("PUT", "/playback/monitor/skip-music", { on: next });
      setSkip(monitor.skip_music);
      engine.current?.apply(monitor);
    } catch (caught) {
      setSkip(!next);
      setError(errorText(caught));
    }
  };

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
              ? skip
                ? "Playing in this browser: beeps for songs, each only until the DJ's next words are ready, and the DJ, jingles and announcements for real."
                : "Playing in this browser: beeps for songs, and the DJ, jingles and announcements for real."
              : "GuildFM plays in browsers, not on the speakers.")}
        </span>
      </span>
      <span className={styles.skip}>
        <span id={skipId}>Skip music when ready</span>
        <Toggle checked={skip} onChange={skipMusic} labelledBy={skipId} />
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
