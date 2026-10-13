import { useState } from "react";
import { Link } from "react-router";
import { api, errorText, type PlaybackState } from "../api";
import { chipLabel, statusTones } from "../live/status";
import { usePlayback } from "../live/usePlayback";
import { Dialog } from "./Dialog";
import { Icon } from "./Icon";
import styles from "./QuickControls.module.css";
import { StatusChip } from "./StatusChip";
import { FormError } from "./TextField";
import { VolumeSlider } from "./VolumeSlider";

/** A floating button for admins that opens play, pause, stop and the office volume. */
export function QuickControls() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { state, apply } = usePlayback();

  const send = async (method: "POST" | "PUT", path: string, body?: unknown) => {
    setBusy(true);
    setError(null);
    try {
      apply(await api<PlaybackState>(method, `/playback${path}`, body));
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  };

  const playing = state?.status === "playing";
  const track = state?.track;

  return (
    <>
      <button
        type="button"
        aria-label="Quick controls"
        aria-haspopup="dialog"
        className={styles.fab}
        onClick={() => setOpen(true)}
      >
        <Icon name="admin" size={24} />
        {playing && <span aria-hidden="true" className={styles.onAir} />}
      </button>

      <Dialog open={open} onClose={() => setOpen(false)} title="Quick controls" corner>
        {state && (
          <div className={styles.now}>
            <span className={styles.nowText}>
              <span className={styles.title}>{track?.title || "Nothing playing"}</span>
              {track?.artist && <span className={styles.artist}>{track.artist}</span>}
            </span>
            <StatusChip tone={statusTones[state.status]}>{chipLabel(state)}</StatusChip>
          </div>
        )}

        <div className={styles.transport}>
          {playing ? (
            <button
              type="button"
              disabled={busy}
              className={`${styles.round} ${styles.primary}`}
              onClick={() => send("POST", "/pause")}
            >
              <Icon name="pause" size={26} />
              Pause
            </button>
          ) : (
            <button
              type="button"
              disabled={busy || state?.status === "offline"}
              className={`${styles.round} ${styles.primary}`}
              onClick={() => send("POST", "/play")}
            >
              <Icon name="play" size={26} />
              Play
            </button>
          )}
          <button
            type="button"
            disabled={busy || !state || state.status === "stopped" || state.status === "offline"}
            className={styles.round}
            onClick={() => send("POST", "/stop")}
          >
            <Icon name="stop" size={22} />
            Stop all
          </button>
        </div>

        {state?.group_volume != null && (
          <VolumeSlider
            label="Whole office"
            strong
            value={state.group_volume}
            onCommit={(volume) => send("PUT", "/volume", { volume })}
          />
        )}
        <FormError message={error} />
        <Link to="/admin" className={styles.more} onClick={() => setOpen(false)}>
          All admin controls
          <Icon name="chevronRight" size={16} />
        </Link>
      </Dialog>
    </>
  );
}
