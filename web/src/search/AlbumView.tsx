import { useEffect, useState } from "react";
import {
  type AlbumDetail,
  api,
  errorText,
  type PlaylistDetail,
  type SearchAlbum,
  type SearchTrack,
} from "../api";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import page from "../pages/Page.module.css";
import search from "./SongSearch.module.css";
import { TrackRow } from "./TrackRow";

const songs = (count: number) => `${count} ${count === 1 ? "song" : "songs"}`;

/** "Album · Fleetwood Mac · 1977 · 11 songs", for an album in search results. */
export function albumLine(album: SearchAlbum): string {
  const kind = album.kind.charAt(0).toUpperCase() + album.kind.slice(1);
  return [kind, album.artists, album.year, songs(album.tracks)].filter(Boolean).join(" · ");
}

function addAllLabel(missing: number, total: number): string {
  if (missing === 0) return "All in the playlist";
  if (missing === total) return missing === 1 ? "Add the song" : `Add all ${songs(missing)}`;
  return missing === 1 ? "Add the other song" : `Add the other ${songs(missing)}`;
}

type Props = {
  album: SearchAlbum;
  playlist: PlaylistDetail;
  onPlaylist: (playlist: PlaylistDetail) => void;
  onAdd: (track: SearchTrack) => void;
  onBack: () => void;
  onAdded: (message: string | null) => void;
  onError: (message: string | null) => void;
};

/** An album's songs, to look over before adding all of them, or some, to a playlist. */
export function AlbumView({ album, playlist, onPlaylist, onAdd, onBack, onAdded, onError }: Props) {
  const [detail, setDetail] = useState<AlbumDetail | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let current = true;
    setDetail(null);
    api<AlbumDetail>("GET", `/albums/${album.id}`)
      .then((found) => current && setDetail(found))
      .catch((caught) => current && onError(errorText(caught)));
    return () => {
      current = false;
    };
  }, [album.id, onError]);

  const inPlaylist = new Set(playlist.items.map((item) => item.id));
  const missing = detail?.items.filter((track) => !inPlaylist.has(track.id)).length ?? 0;
  const minutes = Math.round((detail?.items ?? []).reduce((sum, t) => sum + t.duration, 0) / 60);

  const addAll = async () => {
    setBusy(true);
    onError(null);
    try {
      const updated = await api<PlaylistDetail>("POST", `/playlists/${playlist.id}/albums`, {
        album_id: album.id,
      });
      const added = updated.items.length - playlist.items.length;
      onPlaylist(updated);
      onAdded(`Added ${songs(added)} from ${album.name} to ${playlist.name}.`);
    } catch (caught) {
      onAdded(null);
      onError(errorText(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="album-name" className={page.section}>
      <button type="button" className={search.back} onClick={onBack}>
        <Icon name="back" size={16} strokeWidth={2.4} />
        Back to results
      </button>
      <div className={search.albumTop}>
        {album.art_url ? (
          <img src={album.art_url} alt="" className={search.albumArt} />
        ) : (
          <span aria-hidden="true" className={search.albumArt} />
        )}
        <div className={search.text}>
          <h2 id="album-name" className={search.albumName}>
            {album.name}
          </h2>
          <span className={search.meta}>
            {[album.artists, album.year].filter(Boolean).join(" · ")}
          </span>
          {detail && (
            <span className={search.meta}>
              {songs(detail.items.length)} · {minutes} min
            </span>
          )}
        </div>
      </div>

      {!detail && <p className={page.muted}>Getting the album...</p>}
      {detail && detail.items.length === 0 && (
        <p className={page.muted}>None of this album's songs can play here.</p>
      )}
      {detail && detail.items.length > 0 && (
        <>
          <Button disabled={busy || missing === 0} onClick={addAll} className={search.addAll}>
            {missing > 0 && <Icon name="plus" size={16} strokeWidth={2.6} />}
            {busy ? "Adding..." : addAllLabel(missing, detail.items.length)}
          </Button>
          <ul className={search.results}>
            {detail.items.map((track) => (
              <TrackRow
                key={track.id}
                track={track}
                added={inPlaylist.has(track.id)}
                addedLabel="In playlist"
                capped={false}
                onAdd={onAdd}
              />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
