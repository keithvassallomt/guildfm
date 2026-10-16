import { useState } from "react";
import { Link } from "react-router";
import { api, errorText, type PlaybackState, type PlaybackStatus } from "../api";
import { Icon } from "../components/Icon";
import { Progress } from "../components/Progress";
import { StatusChip } from "../components/StatusChip";
import { FormError } from "../components/TextField";
import { VolumeSlider } from "../components/VolumeSlider";
import { chipLabel, opensAgain, statusTones } from "../live/status";
import { clock, usePlayback } from "../live/usePlayback";
import admin from "./AdminPage.module.css";
import styles from "./Page.module.css";

export function AdminPage() {
  const { state, receivedAt, apply } = usePlayback();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const status = state?.status ?? "stopped";

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Admin</h1>
        {state && <StatusChip tone={statusTones[status]}>{chipLabel(state)}</StatusChip>}
      </header>

      <div className={styles.columns}>
        <div className={styles.stack}>
          <Banner state={state} />
          <section className={styles.card} aria-label="Playback">
            <NowPlaying state={state} receivedAt={receivedAt} />
            <Transport status={status} previous={state?.previous ?? null} busy={busy} send={send} />
            <FormError message={error} />
          </section>
        </div>

        <div className={styles.stack}>
          <Volumes state={state} send={send} />
          <section className={styles.section} aria-labelledby="manage">
            <h2 id="manage" className={styles.sectionTitle}>
              Manage
            </h2>
            <nav aria-labelledby="manage" className={admin.links}>
              <Link to="/admin/users" className={admin.link}>
                <Icon name="users" />
                <span className={admin.linkText}>
                  <span className={admin.linkTitle}>Users</span>
                  <span className={admin.linkHint}>Accounts, roles and password resets</span>
                </span>
                <Icon name="chevronRight" size={18} />
              </Link>
              <Link to="/admin/settings" className={admin.link}>
                <Icon name="admin" />
                <span className={admin.linkText}>
                  <span className={admin.linkTitle}>Settings</span>
                  <span className={admin.linkHint}>
                    Playback hours, voting rules and connections
                  </span>
                </span>
                <Icon name="chevronRight" size={18} />
              </Link>
            </nav>
          </section>
        </div>
      </div>
    </div>
  );
}

function Banner({ state }: { state: PlaybackState | null }) {
  if (state?.status === "overridden") {
    return (
      <div className={`${admin.banner} ${admin.warn}`} role="status">
        <strong>Someone took over from the Sonos or Spotify app</strong>
        GuildFM has stepped aside, announcements included. Press Play to take back control.
      </div>
    );
  }
  if (state?.status === "offline") {
    return (
      <div className={`${admin.banner} ${admin.warn}`} role="status">
        <strong>Can't reach the speakers</strong>
        {state.error}
      </div>
    );
  }
  if (state?.status === "stopped" && state.hours?.open === false) {
    return (
      <div className={admin.banner} role="status">
        <strong>Outside playback hours</strong>
        {opensAgain(state.hours)} Pressing Play overrides that, until Stop or the next closing
        time.
      </div>
    );
  }
  if (state?.status === "stopped") {
    return (
      <div className={admin.banner} role="status">
        <strong>GuildFM isn't playing</strong>
        Anything on the speakers now is someone else's. Press Play to take over.
      </div>
    );
  }
  return null;
}

function NowPlaying({ state, receivedAt }: { state: PlaybackState | null; receivedAt: number }) {
  const track = state?.track;
  if (!track) {
    return <p className={styles.muted}>Nothing on the speakers.</p>;
  }

  const label = !track.ours
    ? "On the speakers"
    : state.status === "paused"
      ? `Paused at ${clock(track.position)}`
      : "Now playing";

  return (
    <div className={admin.now}>
      <div className={admin.nowTop}>
        {track.art_url ? (
          <img src={track.art_url} alt="" className={admin.art} />
        ) : (
          <span className={admin.art} aria-hidden="true" />
        )}
        <div className={admin.nowText}>
          <span className={admin.nowLabel}>{label}</span>
          <span className={admin.nowTitle}>{track.title || "Untitled"}</span>
          <span className={styles.muted}>{track.artist}</span>
        </div>
      </div>
      {track.duration > 0 && (
        <Progress track={track} playing={state.status === "playing"} receivedAt={receivedAt} />
      )}
    </div>
  );
}

type Send = (method: "POST" | "PUT", path: string, body?: unknown) => Promise<void>;

type TransportProps = {
  status: PlaybackStatus;
  previous: PlaybackState["previous"];
  busy: boolean;
  send: Send;
};

function Transport({ status, previous, busy, send }: TransportProps) {
  const driving = status === "playing" || status === "paused" || status === "idle";
  const offline = status === "offline";

  return (
    <div className={admin.transport}>
      <TransportButton icon="previous" label="Previous" disabled={busy || !previous} onClick={() => send("POST", "/previous")} />
      {status === "playing" ? (
        <TransportButton icon="pause" label="Pause" primary disabled={busy} onClick={() => send("POST", "/pause")} />
      ) : (
        <TransportButton icon="play" label="Play" primary disabled={busy || offline} onClick={() => send("POST", "/play")} />
      )}
      <TransportButton icon="skip" label="Skip" disabled={busy || !driving} onClick={() => send("POST", "/skip")} />
      <TransportButton
        icon="stop"
        label="Stop all"
        disabled={busy || offline || status === "stopped"}
        onClick={() => send("POST", "/stop")}
      />
    </div>
  );
}

type TransportButtonProps = {
  icon: "play" | "pause" | "skip" | "previous" | "stop";
  label: string;
  primary?: boolean;
  disabled?: boolean;
  onClick: () => void;
};

function TransportButton({ icon, label, primary, disabled, onClick }: TransportButtonProps) {
  return (
    <span className={admin.control}>
      <button
        type="button"
        aria-label={label}
        disabled={disabled}
        onClick={onClick}
        className={`${admin.round} ${primary ? admin.primary : ""}`}
      >
        <Icon name={icon} size={icon === "stop" ? 24 : 28} />
      </button>
      <span aria-hidden="true" className={admin.controlLabel}>
        {label}
      </span>
    </span>
  );
}

function Volumes({ state, send }: { state: PlaybackState | null; send: Send }) {
  if (!state || state.group_volume === null) return null;
  const inGroup = state.rooms.filter((room) => room.in_group).length;

  return (
    <section className={styles.section} aria-labelledby="volume">
      <div className={admin.sectionTop}>
        <h2 id="volume" className={styles.sectionTitle}>
          Volume
        </h2>
        <span className={styles.muted}>
          {inGroup} of {state.rooms.length} rooms playing together
        </span>
      </div>
      <div className={styles.card}>
        <VolumeSlider
          label="Whole office"
          strong
          value={state.group_volume}
          onCommit={(volume) => send("PUT", "/volume", { volume })}
        />
      </div>
      <ul className={admin.rooms}>
        {state.rooms.map((room) => (
          <li key={room.uid}>
            <VolumeSlider
              label={
                <>
                  <span className={admin.roomName}>{room.name}</span>{" "}
                  <span className={admin.roomModel}>{room.model.replace(/^Sonos /, "")}</span>
                  {room.on_tv && <span className={admin.tag}>TV</span>}
                  {!room.on_tv && !room.in_group && <span className={admin.tag}>Separate</span>}
                </>
              }
              value={room.volume}
              onCommit={(volume) => send("PUT", `/rooms/${room.uid}/volume`, { volume })}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
