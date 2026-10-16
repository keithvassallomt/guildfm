import { useEffect, useRef, useState } from "react";
import {
  api,
  errorText,
  type FoundTrack,
  type PlaylistDetail,
  type QueueState,
  type SearchArtist,
  type SearchResult,
} from "../api";
import { useMe } from "../auth/AuthProvider";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import { FormError } from "../components/TextField";
import { ago } from "../live/status";
import { clock } from "../live/usePlayback";
import page from "../pages/Page.module.css";
import search from "./SongSearch.module.css";

const TYPING_PAUSE_MS = 300;

export type SearchChanges = { q?: string | null; artist?: string | null };

/** Where Add puts a song: in the queue as a request, or into a playlist. */
export type AddTo =
  | { to: "queue"; queue: QueueState | null; onQueue: (queue: QueueState) => void }
  | { to: "playlist"; playlist: PlaylistDetail; onPlaylist: (playlist: PlaylistDetail) => void };

type Props = {
  /** The search, kept wherever the caller likes: the address bar, or local state. */
  query: string;
  artist: string | null;
  onChange: (changes: SearchChanges) => void;
  addTo: AddTo;
  autoFocus?: boolean;
};

/** Search Spotify and add songs: as requests (the Search page and Queue screen) or to a
 *  playlist (the playlist screen). */
export function SongSearch({ query, artist, onChange, addTo, autoFocus }: Props) {
  const [typed, setTyped] = useState(query);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [added, setAdded] = useState<string | null>(null);
  const latest = useRef(0);
  const input = useRef<HTMLInputElement>(null);
  const me = useMe();
  const queue = addTo.to === "queue" ? addTo.queue : null;
  // Admins have no request cap.
  const unlimited = me.role === "admin";
  const capped = !!queue && !unlimited && queue.mine >= queue.request_cap;
  const inPlaylist = new Set(addTo.to === "playlist" ? addTo.playlist.items.map((i) => i.id) : []);
  const isAdded = (track: FoundTrack) =>
    addTo.to === "queue" ? track.queued : inPlaylist.has(track.id);

  // In a dialog, the browser focuses the first button; the search box is what people want.
  useEffect(() => {
    if (!autoFocus) return;
    const frame = window.requestAnimationFrame(() => input.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [autoFocus]);

  const run = async (offset: number, append: boolean) => {
    const request = ++latest.current;
    setLoading(true);
    setError(null);
    try {
      const wanted = new URLSearchParams({ offset: String(offset) });
      if (query.trim()) wanted.set("q", query.trim());
      if (artist) wanted.set("artist", artist);
      const found = await api<SearchResult>("GET", `/search?${wanted}`);
      if (request !== latest.current) return; // a newer search has started
      setResult((current) => {
        if (!append || !current) return found;
        // Spotify's pages can overlap; songs already showing aren't shown twice.
        const shown = new Set(current.tracks.map((track) => track.id));
        return {
          ...found,
          tracks: [...current.tracks, ...found.tracks.filter((track) => !shown.has(track.id))],
        };
      });
    } catch (caught) {
      if (request === latest.current) setError(errorText(caught));
    } finally {
      if (request === latest.current) setLoading(false);
    }
  };

  // Wait for a pause in typing before searching.
  useEffect(() => {
    if (typed === query) return;
    const timer = window.setTimeout(() => onChange({ q: typed }), TYPING_PAUSE_MS);
    return () => window.clearTimeout(timer);
  });

  // Search again whenever the query or artist changes.
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

  const add = async (track: FoundTrack) => {
    setError(null);
    try {
      if (addTo.to === "queue") {
        addTo.onQueue(await api<QueueState>("POST", "/queue", { track_id: track.id }));
        setResult((current) =>
          current && {
            ...current,
            tracks: current.tracks.map((t) => (t.id === track.id ? { ...t, queued: true } : t)),
          },
        );
        setAdded(`Added ${track.title} to the queue.`);
      } else {
        addTo.onPlaylist(
          await api<PlaylistDetail>("POST", `/playlists/${addTo.playlist.id}/tracks`, {
            track_id: track.id,
          }),
        );
        setAdded(`Added ${track.title} to ${addTo.playlist.name}.`);
      }
    } catch (caught) {
      setAdded(null);
      setError(errorText(caught));
    }
  };

  const pickArtist = (picked: SearchArtist) => {
    setTyped("");
    onChange({ q: null, artist: picked.name });
  };

  return (
    <div className={search.search}>
      <div className={search.top}>
        <div className={search.box}>
          <label htmlFor="song-search" className="visually-hidden">
            Search for songs and artists
          </label>
          <Icon name="search" size={20} />
          <input
            ref={input}
            id="song-search"
            type="search"
            value={typed}
            placeholder={artist ? `Search within ${artist}` : "Songs or artists"}
            autoComplete="off"
            spellCheck={false}
            enterKeyHint="search"
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
                onChange({ q: null });
                input.current?.focus();
              }}
            >
              <Icon name="close" size={18} />
            </button>
          )}
        </div>
        {queue && (
          <span className={search.count}>
            Your requests: <strong>{queue.mine}</strong>
            {unlimited ? " (no limit for admins)" : ` of ${queue.request_cap}`}
          </span>
        )}
      </div>

      {artist && (
        <div className={search.filter}>
          <span className={page.muted}>Tracks by</span>
          <button
            type="button"
            className={search.filterChip}
            aria-label={`Stop showing only ${artist}`}
            onClick={() => onChange({ artist: null })}
          >
            {artist}
            <Icon name="close" size={14} strokeWidth={2.4} />
          </button>
        </div>
      )}

      <FormError message={error} />
      <p role="status" className={search.added}>
        {added}
      </p>

      {!result && loading && <p className={page.muted}>Searching...</p>}

      {!result && !loading && !error && (
        <section className={page.empty}>
          <h2 className={page.emptyTitle}>Find something to play</h2>
          <p className={page.emptyText}>Search Spotify for a song or an artist.</p>
        </section>
      )}

      {result && result.artists.length > 0 && (
        <section aria-labelledby="found-artists" className={page.section}>
          <h2 id="found-artists" className={search.heading}>
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
        <section aria-labelledby="found-tracks" className={page.section}>
          <h2 id="found-tracks" className={search.heading}>
            Tracks
          </h2>
          {result.tracks.length === 0 ? (
            <p className={page.muted}>No tracks match that search.</p>
          ) : (
            <ul className={search.results}>
              {result.tracks.map((track) => (
                <TrackRow
                  key={track.id}
                  track={track}
                  added={isAdded(track)}
                  addedLabel={addTo.to === "queue" ? "In queue" : "In playlist"}
                  capped={capped}
                  onAdd={add}
                />
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
            <p className={page.muted}>
              You've used all {queue?.request_cap} requests. You can add more once one of yours
              has played.
            </p>
          )}
          <p className={search.note}>Results from Spotify.</p>
        </section>
      )}
    </div>
  );
}

type RowProps = {
  track: FoundTrack;
  added: boolean;
  addedLabel: string;
  capped: boolean;
  onAdd: (track: FoundTrack) => void;
};

function TrackRow({ track, added, addedLabel, capped, onAdd }: RowProps) {
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
      {added ? (
        <span className={search.queued}>{addedLabel}</span>
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
