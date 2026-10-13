import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import {
  api,
  errorText,
  type FoundTrack,
  type QueueState,
  type SearchArtist,
  type SearchResult,
} from "../api";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import { FormError } from "../components/TextField";
import { useToast } from "../components/Toast";
import { ago } from "../live/status";
import { clock } from "../live/usePlayback";
import { useQueue } from "../live/useQueue";
import styles from "./Page.module.css";
import search from "./SearchPage.module.css";

const TYPING_PAUSE_MS = 300;

export function SearchPage() {
  // The search lives in the address, so Back and refresh keep it.
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  const artist = params.get("artist");
  const [typed, setTyped] = useState(query);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(0);
  const { queue, apply } = useQueue();
  const { show, toast } = useToast();
  const capped = !!queue && queue.mine >= queue.request_cap;

  const add = async (track: FoundTrack) => {
    try {
      apply(await api<QueueState>("POST", "/queue", { track_id: track.id }));
      setResult((current) =>
        current && {
          ...current,
          tracks: current.tracks.map((t) => (t.id === track.id ? { ...t, queued: true } : t)),
        },
      );
      show(`Added ${track.title} to the queue`);
    } catch (caught) {
      show(errorText(caught));
    }
  };

  const update = (changes: { q?: string | null; artist?: string | null }) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setParams(next, { replace: true });
  };

  const run = async (offset: number, append: boolean) => {
    const request = ++latest.current;
    setLoading(true);
    setError(null);
    try {
      const wanted = new URLSearchParams({ offset: String(offset) });
      if (query.trim()) wanted.set("q", query.trim());
      if (artist) wanted.set("artist", artist);
      const page = await api<SearchResult>("GET", `/search?${wanted}`);
      if (request !== latest.current) return; // a newer search has started
      setResult((current) =>
        append && current ? { ...page, tracks: [...current.tracks, ...page.tracks] } : page,
      );
    } catch (caught) {
      if (request === latest.current) setError(errorText(caught));
    } finally {
      if (request === latest.current) setLoading(false);
    }
  };

  // Wait for a pause in typing before searching.
  useEffect(() => {
    if (typed === query) return;
    const timer = window.setTimeout(() => update({ q: typed }), TYPING_PAUSE_MS);
    return () => window.clearTimeout(timer);
  });

  // Search again whenever the query or artist in the address changes.
  useEffect(() => {
    if (!query.trim() && !artist) {
      latest.current++;
      setResult(null);
      setError(null);
      setLoading(false);
      return;
    }
    run(0, false);
  }, [query, artist]);

  const pickArtist = (picked: SearchArtist) => {
    setTyped("");
    update({ q: null, artist: picked.name });
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Search</h1>
        {queue && (
          <span className={search.count}>
            Your requests: <strong>{queue.mine}</strong> of {queue.request_cap}
          </span>
        )}
      </header>

      <div className={search.box}>
        <label htmlFor="search" className="visually-hidden">
          Search for songs and artists
        </label>
        <Icon name="search" size={20} />
        <input
          id="search"
          type="search"
          value={typed}
          placeholder={artist ? `Search within ${artist}` : "Songs or artists"}
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => setTyped(event.target.value)}
          className={search.input}
        />
        {typed && (
          <button
            type="button"
            aria-label="Clear search"
            className={search.clear}
            onClick={() => {
              setTyped("");
              update({ q: null });
            }}
          >
            <Icon name="close" size={18} />
          </button>
        )}
      </div>

      {artist && (
        <div className={search.filter}>
          <span className={styles.muted}>Tracks by</span>
          <button
            type="button"
            className={search.filterChip}
            aria-label={`Stop showing only ${artist}`}
            onClick={() => update({ artist: null })}
          >
            {artist}
            <Icon name="close" size={14} strokeWidth={2.4} />
          </button>
        </div>
      )}

      <FormError message={error} />

      {!result && loading && <p className={styles.muted}>Searching...</p>}

      {!result && !loading && !error && (
        <section className={styles.empty}>
          <h2 className={styles.emptyTitle}>Find something to play</h2>
          <p className={styles.emptyText}>Search Spotify for a song or an artist.</p>
        </section>
      )}

      {result && result.artists.length > 0 && (
        <section aria-labelledby="artists" className={styles.section}>
          <h2 id="artists" className={search.heading}>
            Artists
          </h2>
          <div className={search.artists}>
            {result.artists.map((found) => (
              <button
                key={found.id}
                type="button"
                className={search.artist}
                onClick={() => pickArtist(found)}
              >
                {found.art_url ? (
                  <img src={found.art_url} alt="" className={search.artistArt} />
                ) : (
                  <span aria-hidden="true" className={search.artistArt}>
                    {found.name.charAt(0)}
                  </span>
                )}
                {found.name}
              </button>
            ))}
          </div>
        </section>
      )}

      {result && (
        <section aria-labelledby="tracks" className={styles.section}>
          <h2 id="tracks" className={search.heading}>
            Tracks
          </h2>
          {result.tracks.length === 0 ? (
            <p className={styles.muted}>No tracks match that search.</p>
          ) : (
            <ul className={search.results}>
              {result.tracks.map((track) => (
                <TrackRow key={track.id} track={track} capped={capped} onAdd={add} />
              ))}
            </ul>
          )}
          {result.next_offset !== null && (
            <Button
              variant="secondary"
              disabled={loading}
              onClick={() => run(result.next_offset ?? 0, true)}
              className={search.more}
            >
              {loading ? "Loading..." : "Show more"}
            </Button>
          )}
          {capped && (
            <p className={styles.muted}>
              You've used all {queue?.request_cap} requests. You can add more once one of yours
              has played.
            </p>
          )}
          <p className={search.note}>Results from Spotify.</p>
        </section>
      )}
      {toast}
    </div>
  );
}

type RowProps = { track: FoundTrack; capped: boolean; onAdd: (track: FoundTrack) => void };

function TrackRow({ track, capped, onAdd }: RowProps) {
  return (
    <li className={search.track}>
      {track.art_url ? (
        <img src={track.art_url} alt="" loading="lazy" className={search.art} />
      ) : (
        <span aria-hidden="true" className={search.art} />
      )}
      <span className={search.text}>
        <span className={search.titleLine}>
          <span className={search.title}>{track.title}</span>
          {track.explicit && (
            <abbr title="Explicit" className={search.explicit}>
              E
            </abbr>
          )}
        </span>
        <span className={search.meta}>
          {track.artists} · {clock(track.duration)}
        </span>
        {track.played_at && (
          <span className={search.recent}>
            <Icon name="clock" size={12} strokeWidth={2.4} />
            Played {ago(track.played_at)}
          </span>
        )}
      </span>
      {track.queued ? (
        <span className={search.queued}>In queue</span>
      ) : (
        <Button
          disabled={capped}
          aria-label={capped ? `Add ${track.title}, request limit reached` : `Add ${track.title}`}
          onClick={() => onAdd(track)}
          className={search.add}
        >
          <Icon name="plus" size={16} strokeWidth={2.6} />
          Add
        </Button>
      )}
    </li>
  );
}
