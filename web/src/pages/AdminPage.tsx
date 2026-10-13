import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import {
  api,
  errorText,
  type PlaybackState,
  type PlaybackStatus,
  type SpotifyAccount,
} from "../api";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import { StatusChip } from "../components/StatusChip";
import { FormError, TextField } from "../components/TextField";
import { VolumeSlider } from "../components/VolumeSlider";
import { clock, usePlayback, usePosition } from "../live/usePlayback";
import admin from "./AdminPage.module.css";
import styles from "./Page.module.css";

const statusLabels: Record<PlaybackStatus, string> = {
  playing: "On air",
  paused: "Paused",
  idle: "Nothing playing",
  stopped: "Stopped",
  overridden: "Overridden",
  offline: "Speakers offline",
};

const tones: Record<PlaybackStatus, "live" | "idle" | "warn"> = {
  playing: "live",
  paused: "idle",
  idle: "idle",
  stopped: "idle",
  overridden: "warn",
  offline: "warn",
};

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
        {state && <StatusChip tone={tones[status]}>{statusLabels[status]}</StatusChip>}
      </header>

      <div className={styles.columns}>
        <div className={styles.stack}>
          <Banner state={state} />
          <section className={styles.card} aria-label="Playback">
            <NowPlaying state={state} receivedAt={receivedAt} />
            <Transport status={status} busy={busy} send={send} />
            <FormError message={error} />
          </section>
          <SpotifyTester busy={busy} send={send} />
        </div>

        <div className={styles.stack}>
          <Volumes state={state} send={send} />
          <SpotifyConnection />
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
  const position = usePosition(state, receivedAt);
  const track = state?.track;
  if (!track) {
    return <p className={styles.muted}>Nothing on the speakers.</p>;
  }

  const label = !track.ours
    ? "On the speakers"
    : state.status === "paused"
      ? `Paused at ${clock(position)}`
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
        <div className={admin.progress}>
          <div className={admin.bar}>
            <div
              className={admin.fill}
              style={{ width: `${(100 * position) / track.duration}%` }}
            />
          </div>
          <div className={admin.times}>
            <span>{clock(position)}</span>
            <span>{clock(track.duration)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

type Send = (method: "POST" | "PUT", path: string, body?: unknown) => Promise<void>;

function Transport({ status, busy, send }: { status: PlaybackStatus; busy: boolean; send: Send }) {
  const driving = status === "playing" || status === "paused" || status === "idle";
  const offline = status === "offline";

  return (
    <div className={admin.transport}>
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
  icon: "play" | "pause" | "skip" | "stop";
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

/** Until search arrives, admins can play a Spotify link to try the speakers out. */
function SpotifyTester({ busy, send }: { busy: boolean; send: Send }) {
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const link = String(new FormData(event.currentTarget).get("link") ?? "");
    send("POST", "/spotify", { link });
  };

  return (
    <section className={styles.section} aria-labelledby="tester">
      <h2 id="tester" className={styles.sectionTitle}>
        Play a Spotify link
      </h2>
      <form className={`${styles.card} ${admin.tester}`} onSubmit={submit}>
        <TextField
          label="Track link"
          name="link"
          required
          autoComplete="off"
          placeholder="https://open.spotify.com/track/..."
          hint="For trying the speakers out until the queue arrives in stage 5. Plays straight away."
        />
        <Button type="submit" variant="secondary" disabled={busy}>
          Play now
        </Button>
      </form>
    </section>
  );
}

const THIS_MACHINE = ["127.0.0.1", "localhost", "[::1]"];

const longDate = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });

/** The Spotify account curators import playlists from. */
function SpotifyConnection() {
  const [account, setAccount] = useState<SpotifyAccount | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const load = useCallback(() => {
    api<SpotifyAccount>("GET", "/spotify/account")
      .then(setAccount)
      .catch((caught) => setError(errorText(caught)));
  }, []);

  useEffect(() => {
    load();
    // Connecting happens in another tab, so check again on coming back to this one.
    const onVisible = () => document.visibilityState === "visible" && load();
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [load]);

  const connect = async () => {
    // Open the tab straight away, inside the click, so pop-up blockers allow it.
    const tab = window.open("about:blank", "_blank");
    if (tab) tab.opener = null;
    try {
      const { url } = await api<{ url: string }>("POST", "/spotify/connect");
      if (tab) tab.location.href = url;
      else window.location.assign(url);
    } catch (caught) {
      tab?.close();
      setError(errorText(caught));
    }
  };

  const disconnect = async () => {
    try {
      await api("DELETE", "/spotify/account");
      setConfirming(false);
      load();
    } catch (caught) {
      setError(errorText(caught));
    }
  };

  const onThisMachine = THIS_MACHINE.includes(window.location.hostname);
  const here = `http://127.0.0.1:${window.location.port || "80"}/admin`;

  return (
    <section className={styles.section} aria-labelledby="connections">
      <h2 id="connections" className={styles.sectionTitle}>
        Connections
      </h2>
      <div className={styles.card}>
        <div className={admin.connection}>
          <Icon name="spotify" />
          <span className={admin.linkText}>
            <span className={admin.linkTitle}>Spotify account</span>
            <span className={admin.linkHint}>
              {account?.connected
                ? `Connected as ${account.display_name}${
                    account.playlists !== null ? `, ${account.playlists} playlists` : ""
                  }`
                : "Not connected"}
            </span>
          </span>
        </div>

        {account?.connected && account.reconnect_by && (
          <p className={account.reconnect_soon ? admin.soon : styles.muted}>
            {account.reconnect_soon ? "Reconnect soon: " : ""}Spotify asks for the account to be
            connected again by {longDate(account.reconnect_by)}.
          </p>
        )}
        {account && !account.connected && (
          <p className={styles.muted}>
            Curators import playlists from this account. Only playlists it owns or collaborates
            on can be imported.
          </p>
        )}
        {account?.problem && <p className={admin.soon}>{account.problem}</p>}

        {onThisMachine ? (
          <div className={admin.buttons}>
            <Button variant={account?.connected ? "secondary" : "primary"} onClick={connect}>
              {account?.connected ? "Reconnect" : "Connect Spotify"}
            </Button>
            {account?.connected && !confirming && (
              <Button variant="ghost" onClick={() => setConfirming(true)}>
                Disconnect
              </Button>
            )}
          </div>
        ) : (
          <p className={styles.muted}>
            Spotify only lets GuildFM connect from the machine it runs on. Open{" "}
            <strong>{here}</strong> there, sign in, and connect from this page.
          </p>
        )}

        {confirming && (
          <div className={admin.confirm}>
            <span>Disconnect {account?.display_name}? Curators won't be able to import.</span>
            <span className={admin.buttons}>
              <Button variant="secondary" onClick={() => setConfirming(false)}>
                Cancel
              </Button>
              <Button onClick={disconnect}>Disconnect</Button>
            </span>
          </div>
        )}
        <FormError message={error} />
      </div>
    </section>
  );
}
