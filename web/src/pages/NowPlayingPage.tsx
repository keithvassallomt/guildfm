import { useState } from "react";
import { Link } from "react-router";
import {
  api,
  errorText,
  type Play,
  type PlaybackState,
  type LineupTile,
  type PlaylistTile,
  type QueueEntry,
  type SourceKind,
  type StationTile,
} from "../api";
import { useAuth } from "../auth/AuthProvider";
import { Avatar } from "../components/Avatar";
import { Button } from "../components/Button";
import { Credit } from "../components/Credit";
import { Icon } from "../components/Icon";
import { LogoCover } from "../components/LogoCover";
import { PlaybackBanner } from "../components/PlaybackBanner";
import { Progress } from "../components/Progress";
import { StatusChip } from "../components/StatusChip";
import { useToast } from "../components/Toast";
import { useWide } from "../components/useWide";
import { RoomVolumes } from "../components/RoomVolumes";
import { VolumeSlider } from "../components/VolumeSlider";
import { chipLabel, ownClip, statusTones } from "../live/status";
import { useHistory } from "../live/useHistory";
import { useNow } from "../live/useNow";
import { usePlayback } from "../live/usePlayback";
import { useQueue } from "../live/useQueue";
import n from "./NowPlaying.module.css";
import { Bands, OnAirBars, type Sources, SourceTabs } from "./NowSources";
import styles from "./Page.module.css";
import { QuickAnnouncement } from "./QuickAnnouncement";

const FROM: Record<SourceKind, string> = {
  queue: "the queue",
  library: "the library",
  radio: "the radio",
  lineups: "the line-up",
};

type Send = (method: "POST" | "PUT", path: string, body?: unknown) => Promise<void>;

/** The landing screen: what's playing, where it came from, the sources, and today's plays. */
export function NowPlayingPage() {
  const wide = useWide();
  const { can, me } = useAuth();
  const { state: playback, receivedAt, apply } = usePlayback();
  const { queue } = useQueue();
  const { now } = useNow();
  const history = useHistory();
  const { show, toast } = useToast();
  const [busy, setBusy] = useState(false);
  const [announcing, setAnnouncing] = useState(false);
  const playing = playback?.status === "playing";

  const send: Send = async (method, path, body) => {
    setBusy(true);
    try {
      apply(await api<PlaybackState>(method, `/playback${path}`, body));
    } catch (caught) {
      show(errorText(caught));
    } finally {
      setBusy(false);
    }
  };

  const pick = async (playlist: PlaylistTile) => {
    if (playlist.filling) {
      show(`${playlist.name} is already on.`);
      return;
    }
    try {
      await api("POST", `/playlists/${playlist.id}/play`);
      show(
        playing
          ? `${playlist.name} takes over after this song. Requests still play first.`
          : `${playlist.name} is on. Requests still play first.`,
      );
    } catch (caught) {
      show(errorText(caught));
    }
  };

  const pickStation = async (station: StationTile) => {
    if (station.filling) {
      show(`${station.name} is already on.`);
      return;
    }
    try {
      await api("POST", `/stations/${station.id}/play`);
      show(
        playing
          ? `${station.name} takes over after this song. Requests still play first.`
          : `${station.name} is picking its first songs. Requests still play first.`,
      );
    } catch (caught) {
      show(errorText(caught));
    }
  };

  const pickLineup = async (lineup: LineupTile) => {
    try {
      await api("POST", `/lineups/${lineup.id}/play`);
      show(
        playing
          ? `${lineup.name} takes over after this song. Requests still play first.`
          : `${lineup.name} is on. Requests still play first.`,
      );
    } catch (caught) {
      show(errorText(caught));
    }
  };

  const requestsOnly = async () => {
    if (now?.requests_only) return;
    try {
      await api("DELETE", "/source");
      show(playing ? "After this song, only requests play." : "Only requests play now.");
    } catch (caught) {
      show(errorText(caught));
    }
  };

  const sources: Sources = {
    now,
    queue,
    playing,
    canSwitch: can("switch_source"),
    pick,
    pickStation,
    pickLineup,
    requestsOnly,
  };
  const card = (
    <NowCard
      deck={wide}
      playback={playback}
      receivedAt={receivedAt}
      entry={queue?.playing ?? null}
      onAir={now?.on_air ?? null}
      busy={busy}
      send={send}
      transport={can("transport")}
      office={can("control_playback")}
      onAnnounce={can("announce") ? () => setAnnouncing(true) : null}
    />
  );

  return (
    <div className={`${styles.page} ${n.page}`} data-paused={!playing}>
      <header className={styles.header}>
        <h1 className={styles.title}>Now Playing</h1>
        <div className={n.headerEnd}>
          {playback && (
            <StatusChip tone={statusTones[playback.status]}>{chipLabel(playback)}</StatusChip>
          )}
          {!wide && me && (
            <Link to="/profile" aria-label="Profile" className={n.avatar}>
              <Avatar name={me.display_name} url={me.avatar_url} size={32} />
            </Link>
          )}
        </div>
      </header>

      <PlaybackBanner playback={playback} canPlay={can("transport")} />

      {wide ? (
        <div className={n.split}>
          {card}
          <Bands {...sources} />
        </div>
      ) : (
        <>
          {card}
          <SourceTabs {...sources} />
        </>
      )}

      <HistoryList {...history} />
      <QuickAnnouncement
        open={announcing}
        onClose={() => setAnnouncing(false)}
        onSent={show}
      />
      {toast}
    </div>
  );
}

type NowCardProps = {
  deck: boolean;
  playback: PlaybackState | null;
  receivedAt: number;
  entry: QueueEntry | null;
  onAir: SourceKind | null;
  busy: boolean;
  send: Send;
  transport: boolean;
  office: boolean;
  onAnnounce: (() => void) | null;
};

function NowCard({
  deck,
  playback,
  receivedAt,
  entry,
  onAir,
  busy,
  send,
  transport,
  office,
  onAnnounce,
}: NowCardProps) {
  const track = playback?.track;
  // Spotify's details for GuildFM's own songs, the speakers' for anything else.
  const queued = track?.ours && entry ? entry.track : null;
  const art = queued?.art_url ?? track?.art_url ?? null;
  const live = playback?.status === "playing" && !!track?.ours;
  const label = playback?.announcing
    ? "Announcement playing"
    : playback?.dj_talking
      ? "The DJ is talking"
      : playback?.jingle
      ? "Jingle playing"
      : !track?.ours
      ? "On the speakers"
    : playback?.status === "paused"
      ? "Paused"
      : onAir
        ? `On air from ${FROM[onAir]}`
        : "Now playing";

  return (
    <section aria-label="Now playing" className={`${n.now} ${deck ? n.deck : ""}`}>
      {track ? (
        <>
          <div className={n.nowTop}>
            {playback && ownClip(playback) ? (
              <LogoCover className={n.nowArt} />
            ) : art ? (
              <img src={art} alt="" className={n.nowArt} />
            ) : (
              <span aria-hidden="true" className={n.nowArt} />
            )}
            <div className={n.nowText}>
              <span className={n.nowLabel}>
                {live && <OnAirBars />}
                {label}
              </span>
              <span className={n.nowTitle}>{queued?.title ?? (track.title || "Untitled")}</span>
              <span className={n.nowArtist}>{queued?.artists ?? track.artist}</span>
              {queued && entry && (
                <span className={n.nowFrom}>
                  <Credit entry={entry} />
                </span>
              )}
            </div>
          </div>
          {track.duration > 0 && (
            <Progress track={track} receivedAt={receivedAt} />
          )}
        </>
      ) : (
        <p className={n.nothing}>Nothing playing right now.</p>
      )}
      {playback && transport && <Transport playback={playback} busy={busy} send={send} />}
      {playback && office && (
        <OfficeControls playback={playback} busy={busy} send={send} onAnnounce={onAnnounce} />
      )}
    </section>
  );
}

type ControlsProps = { playback: PlaybackState; busy: boolean; send: Send };

function Transport({ playback, busy, send }: ControlsProps) {
  const status = playback.status;
  const driving = status === "playing" || status === "paused" || status === "idle";
  return (
    <div className={n.transport}>
      <button
        type="button"
        aria-label="Previous"
        title="Previous"
        disabled={busy || !playback.previous}
        className={n.round}
        onClick={() => send("POST", "/previous")}
      >
        <Icon name="previous" size={22} />
      </button>
      {status === "playing" ? (
        <button
          type="button"
          aria-label="Pause"
          disabled={busy}
          className={`${n.round} ${n.play}`}
          onClick={() => send("POST", "/pause")}
        >
          <Icon name="pause" size={28} />
        </button>
      ) : (
        <button
          type="button"
          aria-label="Play"
          disabled={busy || status === "offline"}
          className={`${n.round} ${n.play}`}
          onClick={() => send("POST", "/play")}
        >
          <Icon name="play" size={28} />
        </button>
      )}
      <button
        type="button"
        aria-label="Skip"
        title="Skip"
        disabled={busy || !driving}
        className={n.round}
        onClick={() => send("POST", "/skip")}
      >
        <Icon name="skip" size={22} />
      </button>
    </div>
  );
}

type OfficeProps = ControlsProps & { onAnnounce: (() => void) | null };

/** For admins: the volume, room by room if they like, Stop all, and a quick announcement. */
function OfficeControls({ playback, busy, send, onAnnounce }: OfficeProps) {
  const [rooms, setRooms] = useState(false);
  const together = playback.rooms.filter((room) => room.in_group).length;
  return (
    <div className={n.office}>
      {playback.group_volume != null && (
        <VolumeSlider
          label="Whole office"
          strong
          value={playback.group_volume}
          onCommit={(volume) => send("PUT", "/volume", { volume })}
        />
      )}
      {playback.rooms.length > 0 && (
        <button
          type="button"
          aria-expanded={rooms}
          className={n.roomsToggle}
          onClick={() => setRooms(!rooms)}
        >
          <Icon name="chevronDown" size={16} />
          Rooms
          <span className={n.roomsNote}>
            {together} of {playback.rooms.length} playing together
          </span>
        </button>
      )}
      {rooms && (
        <RoomVolumes
          rooms={playback.rooms}
          onVolume={(uid, volume) => send("PUT", `/rooms/${uid}/volume`, { volume })}
        />
      )}
      <div className={n.officeButtons}>
        {onAnnounce && (
          <button type="button" className={n.stop} onClick={onAnnounce}>
            <Icon name="announce" size={16} />
            Announce
          </button>
        )}
        <button
          type="button"
          disabled={busy || playback.status === "stopped" || playback.status === "offline"}
          className={n.stop}
          onClick={() => send("POST", "/stop")}
        >
          <Icon name="stop" size={16} />
          Stop all
        </button>
      </div>
    </div>
  );
}

function source(play: Play): string {
  if (play.requested_by) {
    const votes = play.upvotes - play.downvotes;
    return `Requested by ${play.requested_by.display_name}${votes > 0 ? ` · +${votes}` : ""}`;
  }
  return play.playlist ?? play.station ?? "Played";
}

function time(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

type HistoryProps = { plays: Play[] | null; more: boolean; showMore: () => Promise<void> };

function HistoryList({ plays, more, showMore }: HistoryProps) {
  return (
    <section className={styles.section} aria-labelledby="history">
      <div className={n.sectionTop}>
        <h2 id="history" className={styles.sectionTitle}>
          Played today
        </h2>
        <span className={n.sectionNote}>Newest first</span>
      </div>
      {plays && plays.length === 0 && <p className={styles.muted}>Nothing has played yet today.</p>}
      <ol className={n.history}>
        {plays?.map((play) => (
          <li key={play.id} className={n.played}>
            {play.track.art_url ? (
              <img src={play.track.art_url} alt="" className={n.playedArt} />
            ) : (
              <span aria-hidden="true" className={n.playedArt} />
            )}
            <span className={n.playedText}>
              <span className={n.playedTitle}>{play.track.title}</span>
              <span className={n.playedMeta}>
                {play.requested_by ? (
                  <Avatar
                    name={play.requested_by.display_name}
                    url={play.requested_by.avatar_url}
                    size={14}
                  />
                ) : (
                  <Icon name={play.station ? "radio" : "library"} size={12} />
                )}
                <span>
                  {play.track.artists} · {source(play)}
                </span>
              </span>
            </span>
            <span className={n.playedAt}>{time(play.played_at)}</span>
          </li>
        ))}
      </ol>
      {more && (
        <Button variant="secondary" className={n.more} onClick={() => showMore().catch(() => {})}>
          Show more
        </Button>
      )}
    </section>
  );
}
