import { useState } from "react";
import { api, errorText, type PlaybackState, type QueueEntry, type QueueState } from "../api";
import { useAuth } from "../auth/AuthProvider";
import { Button } from "../components/Button";
import { Dialog } from "../components/Dialog";
import { Credit } from "../components/Credit";
import { Icon } from "../components/Icon";
import { LogoCover } from "../components/LogoCover";
import { PlaybackBanner } from "../components/PlaybackBanner";
import { Progress } from "../components/Progress";
import { StatusChip } from "../components/StatusChip";
import { useToast } from "../components/Toast";
import { ago, chipLabel, ownClip, statusTones } from "../live/status";
import { usePlayback } from "../live/usePlayback";
import { useQueue } from "../live/useQueue";
import { type SearchChanges, SongSearch } from "../search/SongSearch";
import styles from "./Page.module.css";
import q from "./QueuePage.module.css";
import { type Act, Requests, Upcoming } from "./QueueRequests";


export function QueuePage() {
  const { can } = useAuth();
  const { queue, apply, refresh } = useQueue();
  const { state: playback, receivedAt } = usePlayback();
  const { show, toast } = useToast();
  const curator = can("manage_queue");
  const [searching, setSearching] = useState(false);

  const act: Act = async (method, path, body, done) => {
    try {
      apply(await api<QueueState>(method, path, body));
      if (done) show(done);
    } catch (caught) {
      show(errorText(caught));
    }
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Queue</h1>
        {playback && (
          <StatusChip tone={statusTones[playback.status]}>{chipLabel(playback)}</StatusChip>
        )}
      </header>

      <PlaybackBanner playback={playback} />

      <div className={q.layout}>
        <div className={q.now}>
          <NowPlaying playback={playback} receivedAt={receivedAt} entry={queue?.playing ?? null} />
        </div>
        {queue?.next && (
          <div className={q.next}>
            <UpNext entry={queue.next} />
          </div>
        )}
        <section className={`${styles.section} ${q.requests}`} aria-labelledby="requests">
          <div className={q.sectionTop}>
            <h2 id="requests" className={styles.sectionTitle}>
              Requests
            </h2>
            {queue && (
              <span className={styles.muted}>
                Sorted by votes · {queue.mine} of {queue.request_cap} yours
              </span>
            )}
          </div>
          <button type="button" className={q.requestBar} onClick={() => setSearching(true)}>
            <Icon name="search" size={20} />
            Search for a song to request
          </button>
          {queue && queue.waiting.length === 0 && (
            <div className={styles.empty}>
              <p className={styles.emptyText}>Nothing requested yet. Find a song to get it going.</p>
              <Button onClick={() => setSearching(true)}>
                <Icon name="plus" size={18} strokeWidth={2.6} />
                Request a song
              </Button>
            </div>
          )}
          {queue && queue.waiting.length > 0 && (
            <Requests entries={queue.waiting} curator={curator} act={act} />
          )}
          {queue?.source && (
            <Upcoming
              source={queue.source}
              onThumb={async (track_id, down) => {
                try {
                  const { skipped } = await api<{ skipped: boolean }>("POST", "/source/vote", {
                    track_id,
                    down,
                  });
                  if (skipped) show("That song will be skipped this time round");
                } catch (caught) {
                  show(errorText(caught));
                }
                refresh();
              }}
            />
          )}
        </section>
        <section className={`${styles.section} ${q.activity}`} aria-labelledby="activity">
          <h2 id="activity" className={styles.sectionTitle}>
            Activity
          </h2>
          {queue && queue.activity.length === 0 && (
            <p className={styles.muted}>Nothing yet. Requests and votes show up here.</p>
          )}
          <ul className={q.feed}>
            {queue?.activity.map((item) => (
              <li key={`${item.at}-${item.text}`}>
                <span>{item.text}</span>
                <span className={q.when}>{ago(item.at)}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
      <QuickSearch open={searching} onClose={() => setSearching(false)} queue={queue} onQueue={apply} />
      {toast}
    </div>
  );
}

type QuickSearchProps = {
  open: boolean;
  onClose: () => void;
  queue: QueueState | null;
  onQueue: (queue: QueueState) => void;
};

/** Search and request without leaving the queue. Each time it opens, it starts afresh. */
function QuickSearch({ open, onClose, queue, onQueue }: QuickSearchProps) {
  const [search, setSearch] = useState<{ q: string; artist: string | null }>({
    q: "",
    artist: null,
  });

  const close = () => {
    setSearch({ q: "", artist: null });
    onClose();
  };

  const update = (changes: SearchChanges) =>
    setSearch((current) => ({
      q: changes.q === undefined ? current.q : (changes.q ?? ""),
      artist: changes.artist === undefined ? current.artist : changes.artist,
    }));

  return (
    <Dialog open={open} onClose={close} title="Request a song" tall>
      <SongSearch
        query={search.q}
        artist={search.artist}
        onChange={update}
        addTo={{ to: "queue", queue, onQueue }}
        autoFocus
      />
    </Dialog>
  );
}

type NowProps = { playback: PlaybackState | null; receivedAt: number; entry: QueueEntry | null };

function NowPlaying({ playback, receivedAt, entry }: NowProps) {
  const track = playback?.track;
  if (!track) {
    return (
      <section className={q.card} aria-label="Now playing">
        <p className={styles.muted}>Nothing playing right now.</p>
      </section>
    );
  }
  // Spotify's details for GuildFM's own songs, the speakers' for anything else.
  const queued = track.ours && entry ? entry.track : null;
  const label = !track.ours
    ? "On the speakers"
    : playback.status === "paused"
      ? "Paused"
      : "Now playing";

  return (
    <section className={q.card} aria-label="Now playing">
      <div className={q.nowTop}>
        {ownClip(playback) ? (
          <LogoCover className={`${q.art} ${q.artLarge}`} />
        ) : (
          <Art url={queued?.art_url ?? track.art_url} size="large" />
        )}
        <div className={q.text}>
          <span className={q.label}>{label}</span>
          <span className={q.nowTitle}>{queued?.title ?? (track.title || "Untitled")}</span>
          <span className={styles.muted}>{queued?.artists ?? track.artist}</span>
        </div>
      </div>
      {track.duration > 0 && (
        <Progress track={track} receivedAt={receivedAt} />
      )}
      {queued && entry && (
        <span className={q.requested}>
          <Credit entry={entry} size={18} />
        </span>
      )}
    </section>
  );
}

function UpNext({ entry }: { entry: QueueEntry }) {
  return (
    <section className={styles.section} aria-labelledby="up-next">
      <h2 id="up-next" className={styles.sectionTitle}>
        Up next
      </h2>
      <div className={q.locked}>
        <Icon name="lock" size={18} />
        <Art url={entry.track.art_url} />
        <div className={q.text}>
          <span className={q.title}>{entry.track.title}</span>
          <span className={q.meta}>
            {entry.track.artists} · <Credit entry={entry} />
          </span>
        </div>
        <span className={q.lockedNote}>Locked in, already sent to the speakers</span>
      </div>
    </section>
  );
}

function Art({ url, size }: { url: string | null; size?: "large" }) {
  const className = `${q.art} ${size === "large" ? q.artLarge : ""}`;
  return url ? (
    <img src={url} alt="" className={className} />
  ) : (
    <span aria-hidden="true" className={className} />
  );
}
