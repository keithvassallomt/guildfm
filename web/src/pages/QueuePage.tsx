import { api, errorText, type PlaybackState, type QueueEntry, type QueueState } from "../api";
import { useAuth } from "../auth/AuthProvider";
import { ButtonLink } from "../components/Button";
import { Icon } from "../components/Icon";
import { Logo } from "../components/Logo";
import { StatusChip } from "../components/StatusChip";
import { useToast } from "../components/Toast";
import { ago, statusLabels, statusTones } from "../live/status";
import { clock, usePlayback, usePosition } from "../live/usePlayback";
import { useQueue } from "../live/useQueue";
import styles from "./Page.module.css";
import q from "./QueuePage.module.css";

type Act = (method: "POST" | "DELETE", path: string, body?: unknown, done?: string) => void;

export function QueuePage() {
  const { can } = useAuth();
  const { queue, apply } = useQueue();
  const { state: playback, receivedAt } = usePlayback();
  const { show, toast } = useToast();
  const curator = can("manage_queue");

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
        <h1 className={styles.title}>
          <span className={styles.narrowOnly}>
            <Logo />
          </span>
          <span className={styles.wideOnly}>Queue</span>
        </h1>
        {playback && (
          <StatusChip tone={statusTones[playback.status]}>
            {statusLabels[playback.status]}
          </StatusChip>
        )}
      </header>

      <Banner playback={playback} />

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
          {queue && queue.waiting.length === 0 && (
            <div className={styles.empty}>
              <p className={styles.emptyText}>Nothing requested yet. Find a song to get it going.</p>
              <ButtonLink to="/search">
                <Icon name="plus" size={18} strokeWidth={2.6} />
                Request a song
              </ButtonLink>
            </div>
          )}
          {queue && queue.waiting.length > 0 && (
            <ol className={q.list}>
              {queue.waiting.map((entry, index) => (
                <Request
                  key={entry.id}
                  entry={entry}
                  rank={index + 1}
                  first={index === 0}
                  last={index === queue.waiting.length - 1}
                  curator={curator}
                  act={act}
                />
              ))}
            </ol>
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
      {toast}
    </div>
  );
}

function Banner({ playback }: { playback: PlaybackState | null }) {
  const messages: Partial<Record<string, [string, string]>> = {
    stopped: ["The music is stopped", "Requests still queue up, and play once it starts again."],
    overridden: [
      "Someone's playing something from the Sonos app",
      "GuildFM carries on when an admin takes the speakers back.",
    ],
    offline: ["Can't reach the speakers", "Requests still queue up in the meantime."],
  };
  const message = playback && messages[playback.status];
  if (!message) return null;
  return (
    <div className={`${q.banner} ${playback.status === "stopped" ? "" : q.warn}`} role="status">
      <strong>{message[0]}</strong>
      {message[1]}
    </div>
  );
}

type NowProps = { playback: PlaybackState | null; receivedAt: number; entry: QueueEntry | null };

function NowPlaying({ playback, receivedAt, entry }: NowProps) {
  const position = usePosition(playback, receivedAt);
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
        <Art url={queued?.art_url ?? track.art_url} size="large" />
        <div className={q.text}>
          <span className={q.label}>{label}</span>
          <span className={q.nowTitle}>{queued?.title ?? (track.title || "Untitled")}</span>
          <span className={styles.muted}>{queued?.artists ?? track.artist}</span>
        </div>
      </div>
      {track.duration > 0 && (
        <div className={q.progress}>
          <div className={q.bar}>
            <div className={q.fill} style={{ width: `${(100 * position) / track.duration}%` }} />
          </div>
          <div className={q.times}>
            <span>{clock(position)}</span>
            <span>{clock(track.duration)}</span>
          </div>
        </div>
      )}
      {queued && entry && (
        <span className={q.requested}>Requested by {entry.mine ? "you" : entry.requested_by.display_name}</span>
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
            {entry.track.artists} · Requested by {entry.mine ? "you" : entry.requested_by.display_name}
          </span>
        </div>
        <span className={q.lockedNote}>Locked in, already sent to the speakers</span>
      </div>
    </section>
  );
}

type RequestProps = {
  entry: QueueEntry;
  rank: number;
  first: boolean;
  last: boolean;
  curator: boolean;
  act: Act;
};

function Request({ entry, rank, first, last, curator, act }: RequestProps) {
  const title = entry.track.title;
  const voteFor = (value: -1 | 1) =>
    act("POST", `/queue/${entry.id}/vote`, { value: entry.my_vote === value ? 0 : value });
  const scoreClass = entry.my_vote === 1 ? q.up : entry.my_vote === -1 ? q.down : "";

  return (
    <li className={q.request}>
      <div className={q.requestTop}>
        <span className={q.rank}>{rank}</span>
        <Art url={entry.track.art_url} />
        <div className={q.text}>
          <span className={q.titleLine}>
            <span className={q.title}>{title}</span>
            {entry.track.explicit && (
              <abbr title="Explicit" className={q.explicit}>
                E
              </abbr>
            )}
          </span>
          <span className={q.meta}>{entry.track.artists}</span>
        </div>
        <div className={q.votes}>
          <button
            type="button"
            aria-label={`Thumbs up for ${title}`}
            aria-pressed={entry.my_vote === 1}
            className={`${q.vote} ${entry.my_vote === 1 ? q.up : ""}`}
            onClick={() => voteFor(1)}
          >
            <Icon name="thumbUp" size={20} filled={entry.my_vote === 1} />
          </button>
          <span className={`${q.score} ${scoreClass}`} aria-label={`Score ${entry.score}`}>
            {entry.score > 0 ? `+${entry.score}` : entry.score}
          </span>
          <button
            type="button"
            aria-label={`Thumbs down for ${title}`}
            aria-pressed={entry.my_vote === -1}
            className={`${q.vote} ${entry.my_vote === -1 ? q.down : ""}`}
            onClick={() => voteFor(-1)}
          >
            <Icon name="thumbDown" size={20} filled={entry.my_vote === -1} />
          </button>
        </div>
      </div>
      <div className={q.requestBottom}>
        <span className={q.meta}>
          Requested by {entry.mine ? "you" : entry.requested_by.display_name}
          {entry.pinned && " · placed by a curator"}
        </span>
        {entry.played_at && (
          <span className={q.recent}>
            <Icon name="clock" size={12} strokeWidth={2.4} />
            Played {ago(entry.played_at)}
          </span>
        )}
        {curator && (
          <>
            <button
              type="button"
              aria-label={`Move ${title} up`}
              disabled={first}
              className={q.action}
              onClick={() => act("POST", `/queue/${entry.id}/move`, { direction: "up" })}
            >
              <Icon name="arrowUp" size={18} />
            </button>
            <button
              type="button"
              aria-label={`Move ${title} down`}
              disabled={last}
              className={q.action}
              onClick={() => act("POST", `/queue/${entry.id}/move`, { direction: "down" })}
            >
              <Icon name="arrowDown" size={18} />
            </button>
          </>
        )}
        {(entry.mine || curator) && (
          <button
            type="button"
            aria-label={`Remove ${title}`}
            className={q.action}
            onClick={() => act("DELETE", `/queue/${entry.id}`, undefined, `Removed ${title}`)}
          >
            <Icon name="close" size={18} />
          </button>
        )}
      </div>
    </li>
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
