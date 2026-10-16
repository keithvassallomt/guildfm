import type { SearchTrack } from "../api";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import { ago } from "../live/status";
import { clock } from "../live/usePlayback";
import search from "./SongSearch.module.css";

type RowProps = {
  track: SearchTrack & { played_at?: string | null };
  added: boolean;
  addedLabel: string;
  capped: boolean;
  onAdd: (track: SearchTrack) => void;
};

/** A song in search results or on an album, with its Add button. */
export function TrackRow({ track, added, addedLabel, capped, onAdd }: RowProps) {
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
