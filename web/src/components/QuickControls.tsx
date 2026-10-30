import { useState } from "react";
import { Link } from "react-router";
import { api, COMMAND_TIMEOUT, errorText, type PlaybackState } from "../api";
import { chipLabel, statusTones } from "../live/status";
import { usePlayback } from "../live/usePlayback";
import { Dialog } from "./Dialog";
import { Icon } from "./Icon";
import { Marquee } from "./Marquee";
import styles from "./QuickControls.module.css";
import { StatusChip } from "./StatusChip";
import { FormError } from "./TextField";
import { VolumeSlider } from "./VolumeSlider";

/** A floating button for admins that opens the transport controls and the office volume. */
export function QuickControls() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { state, apply } = usePlayback();

  const send = async (method: "POST" | "PUT", path: string, body?: unknown) => {
    setBusy(true);
    setError(null);
    try {
      apply(await api<PlaybackState>(method, `/playback${path}`, body, COMMAND_TIMEOUT));
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  };

  const status = state?.status;
  const playing = status === "playing";
  const driving = playing || status === "paused" || status === "idle";
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
              <Marquee key={track?.title} className={styles.title}>
                {track?.title || "Nothing playing"}
              </Marquee>
              {track?.artist && <span className={styles.artist}>{track.artist}</span>}
            </span>
            <StatusChip tone={statusTones[state.status]}>{chipLabel(state)}</StatusChip>
          </div>
        )}

        <div className={styles.transport}>
          <button
            type="button"
            aria-label="Previous"
            title="Previous"
            disabled={busy || !state?.previous}
            className={styles.round}
            onClick={() => send("POST", "/previous")}
          >
            <Icon name="previous" size={22} />
          </button>
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
              disabled={busy || status === "offline"}
              className={`${styles.round} ${styles.primary}`}
              onClick={() => send("POST", "/play")}
            >
              <Icon name="play" size={26} />
              Play
            </button>
          )}
          <button
            type="button"
            aria-label="Skip"
            title="Skip"
            disabled={busy || !driving}
            className={styles.round}
            onClick={() => send("POST", "/skip")}
          >
            <Icon name="skip" size={22} />
          </button>
          <button
            type="button"
            disabled={busy || !state || status === "stopped" || status === "offline"}
            className={`${styles.round} ${styles.stop}`}
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
