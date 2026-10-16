import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiUpload, errorText, type Jingle } from "../api";
import { clock } from "../live/usePlayback";
import { Button } from "./Button";
import { Icon } from "./Icon";
import { FormError } from "./TextField";
import styles from "./JingleList.module.css";

/** "Guild_FM_sting.mp3" becomes "Guild FM sting". */
function nameOf(file: File): string {
  const name = file.name.replace(/\.[^.]+$/, "").replace(/_+/g, " ").trim();
  return (name || "Jingle").slice(0, 100);
}

type Props = {
  /** A station's own idents, or the system idents for null. */
  stationId: number | null;
  /** Shown when there are none yet. */
  empty: string;
};

/** Jingles to listen to here, add and remove. Adding takes MP3s, several at once. */
export function JingleList({ stationId, empty }: Props) {
  const [jingles, setJingles] = useState<Jingle[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [playing, setPlaying] = useState<number | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const files = useRef<HTMLInputElement>(null);
  const query = stationId === null ? "" : `?station_id=${stationId}`;

  const load = useCallback(() => {
    api<Jingle[]>("GET", `/jingles${query}`)
      .then(setJingles)
      .catch((caught) => setError(errorText(caught)));
  }, [query]);
  useEffect(load, [load]);

  const stop = useCallback(() => {
    audio.current?.pause();
    audio.current = null;
    setPlaying(null);
  }, []);
  useEffect(() => stop, [stop]);

  const listen = (jingle: Jingle) => {
    if (playing === jingle.id) {
      stop();
      return;
    }
    stop();
    audio.current = new Audio(jingle.url);
    audio.current.onended = stop;
    setPlaying(jingle.id);
    audio.current.play().catch(() => {
      stop();
      setError("Couldn't play that here.");
    });
  };

  const add = async (chosen: FileList | null) => {
    if (!chosen?.length) return;
    setAdding(true);
    setError(null);
    const start = stationId === null ? "" : `&station_id=${stationId}`;
    try {
      for (const file of Array.from(chosen)) {
        const name = encodeURIComponent(nameOf(file));
        await apiUpload<Jingle>(`/jingles?name=${name}${start}`, file, "POST");
      }
    } catch (caught) {
      // A failed fetch is a TypeError; anything else here has a message fit to show.
      setError(caught instanceof Error && !(caught instanceof TypeError) ? caught.message : errorText(caught));
    } finally {
      setAdding(false);
      if (files.current) files.current.value = "";
      load();
    }
  };

  const remove = async (jingle: Jingle) => {
    if (playing === jingle.id) stop();
    setError(null);
    try {
      await api("DELETE", `/jingles/${jingle.id}`);
    } catch (caught) {
      setError(errorText(caught));
    }
    load();
  };

  return (
    <div className={styles.jingles}>
      {jingles && jingles.length === 0 && <p className={styles.empty}>{empty}</p>}
      {jingles && jingles.length > 0 && (
        <ul className={styles.list}>
          {jingles.map((jingle) => (
            <li key={jingle.id} className={styles.row}>
              <button
                type="button"
                className={`${styles.play} ${playing === jingle.id ? styles.on : ""}`}
                aria-label={playing === jingle.id ? `Stop ${jingle.name}` : `Play ${jingle.name}`}
                onClick={() => listen(jingle)}
              >
                <Icon name={playing === jingle.id ? "stop" : "play"} size={14} />
              </button>
              <span className={styles.text}>
                <span className={styles.name}>{jingle.name}</span>
                <span className={styles.length}>{clock(jingle.seconds)}</span>
              </span>
              <Button variant="ghost" className={styles.remove} onClick={() => remove(jingle)}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
      <input
        ref={files}
        type="file"
        accept=".mp3,audio/mpeg"
        multiple
        hidden
        onChange={(event) => add(event.target.files)}
      />
      <div className={styles.foot}>
        <Button variant="secondary" disabled={adding} onClick={() => files.current?.click()}>
          <Icon name="plus" size={16} />
          {adding ? "Adding..." : "Add MP3s"}
        </Button>
        <span className={styles.hint}>
          Up to a minute each. Previews play on this device, not the speakers.
        </span>
      </div>
      <FormError message={error} />
    </div>
  );
}
