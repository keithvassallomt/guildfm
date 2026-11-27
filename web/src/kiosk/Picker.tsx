import { useEffect, useRef, useState } from "react";
import { api, type Favourite, type SearchResult, type SearchTrack } from "../api";
import { Icon } from "../components/Icon";
import { bigArt } from "./art";
import k from "./Kiosk.module.css";

/** How long the picker stays open without a touch, so the next person finds the wall. */
const IDLE_MS = 60_000;
const SEARCH_DELAY_MS = 300;
const ROWS = ["1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"];

export type Pick = { track: SearchTrack; blocked: boolean; note: string };

type Props = {
  favourites: Favourite[];
  playingId: string | null;
  places: string;
  warn: boolean;
  onPick: (track: SearchTrack, cover: HTMLElement | null) => void;
  onClose: () => void;
};

/** The full-screen picker: the office favourites, and search typed on the kiosk's own keyboard. */
export function Picker({ favourites, playingId, places, warn, onPick, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [typing, setTyping] = useState(false);
  const [found, setFound] = useState<SearchTrack[] | null>(null);
  const [queued, setQueued] = useState<Set<string>>(new Set());
  const idle = useRef<number | undefined>(undefined);
  const close = useRef(onClose);
  close.current = onClose;

  const touched = () => {
    window.clearTimeout(idle.current);
    idle.current = window.setTimeout(() => close.current(), IDLE_MS);
  };
  useEffect(() => {
    touched();
    return () => window.clearTimeout(idle.current);
  }, []);

  const term = query.trim();
  useEffect(() => {
    if (term.length < 2) {
      setFound(null);
      return;
    }
    let stale = false;
    const timer = window.setTimeout(() => {
      api<SearchResult>("GET", `/search?q=${encodeURIComponent(term)}`)
        .then((result) => {
          if (stale) return;
          setFound(result.tracks);
          setQueued(new Set(result.tracks.filter((track) => track.queued).map((track) => track.id)));
        })
        .catch(() => !stale && setFound([]));
    }, SEARCH_DELAY_MS);
    return () => {
      stale = true;
      window.clearTimeout(timer);
    };
  }, [term]);

  const picks: Pick[] = found
    ? found.slice(0, 12).map((track) => {
        const playing = track.id === playingId;
        const blocked = playing || queued.has(track.id);
        return { track, blocked, note: playing ? "Playing now" : blocked ? "In the queue" : track.artists };
      })
    : favourites.map(({ track, queued, playing }) => ({
        track,
        blocked: queued || playing,
        note: playing ? "Playing now" : queued ? "In the queue" : track.artists,
      }));
  const label = found
    ? found.length === 1
      ? "1 MATCH"
      : `${Math.min(found.length, 12)} MATCHES`
    : term.length >= 2
      ? "SEARCHING"
      : "OFFICE FAVOURITES · BEST VOTED";

  const type = (text: string) => setQuery((before) => (before + text).slice(0, 40));

  return (
    <div role="dialog" aria-label="Add a song" className={k.picker} onPointerDown={touched}>
      <div className={k.pickerHead}>
        <div className={k.pickerTop}>
          <div>
            <h2 className={k.pickerTitle}>Add a song</h2>
            <span className={`${k.pickerPlaces} ${warn ? k.pickerWarn : ""}`}>{places}</span>
          </div>
          <button type="button" className={k.close} onClick={onClose}>
            <Icon name="close" strokeWidth={2.4} />
            Back to the queue
          </button>
        </div>
        <button
          type="button"
          className={`${k.field} ${typing ? k.fieldTyping : ""}`}
          onClick={() => setTyping(true)}
          aria-label="Search for a song or artist"
        >
          <Icon name="search" strokeWidth={2.2} />
          <span className={k.fieldText} aria-live="polite">
            {query && <span>{query}</span>}
            {typing && <span className={k.caret} />}
            {!query && <span className={k.placeholder}>Search any song or artist</span>}
          </span>
        </button>
      </div>

      <div className={k.pickerBody}>
        <span className={k.pickerLabel}>{label}</span>
        <div className={k.grid}>
          {picks.map((pick, index) => (
            <button
              key={pick.track.id}
              type="button"
              className={k.tile}
              style={{ animationDelay: `${index * 45}ms` }}
              disabled={pick.blocked}
              aria-label={
                pick.blocked
                  ? `${pick.track.title}: ${pick.note.toLowerCase()}`
                  : `Add ${pick.track.title} by ${pick.track.artists}`
              }
              onClick={(event) =>
                onPick(pick.track, event.currentTarget.querySelector<HTMLElement>("[data-cover]"))
              }
            >
              <span className={k.tileCover} data-cover="">
                {pick.track.art_url && <img src={bigArt(pick.track.art_url) ?? undefined} alt="" />}
                <span className={k.tileBadge}>
                  <Icon name={pick.blocked ? "check" : "plus"} strokeWidth={3} />
                </span>
              </span>
              <span className={k.tileTitle}>{pick.track.title}</span>
              <span className={k.tileSub}>{pick.note}</span>
            </button>
          ))}
        </div>
        {found?.length === 0 && (
          <p className={k.empty}>Nothing matches that yet. Try fewer letters, or the artist's name.</p>
        )}
        {!found && term.length < 2 && favourites.length === 0 && (
          <p className={k.empty}>Search for any song: tap the box above to type.</p>
        )}
      </div>

      {typing && (
        <div className={k.keyboard}>
          {ROWS.map((row, index) => (
            <div key={row} className={k.keyRow}>
              {row.split("").map((key) => (
                <button key={key} type="button" className={k.key} onClick={() => type(key.toLowerCase())}>
                  {key}
                </button>
              ))}
              {index === ROWS.length - 1 && (
                <button
                  type="button"
                  className={`${k.key} ${k.keyWide}`}
                  aria-label="Delete"
                  onClick={() => setQuery((before) => before.slice(0, -1))}
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M21 4H8l-7 8 7 8h13a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2Z" />
                    <path d="m18 9-6 6M12 9l6 6" />
                  </svg>
                </button>
              )}
            </div>
          ))}
          <div className={k.keyRow}>
            <button type="button" className={`${k.key} ${k.keyWide}`} onClick={() => setQuery("")}>
              Clear
            </button>
            <button type="button" className={`${k.key} ${k.keySpace}`} onClick={() => type(" ")}>
              Space
            </button>
            <button type="button" className={`${k.key} ${k.keyDone}`} onClick={() => setTyping(false)}>
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
