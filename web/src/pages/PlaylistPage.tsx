import { type FormEvent, useCallback, useEffect, useId, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api, errorText, type PlaylistDetail } from "../api";
import { Button } from "../components/Button";
import { Dialog } from "../components/Dialog";
import { HelpLink } from "../components/HelpLink";
import { Icon } from "../components/Icon";
import { FormError, TextField } from "../components/TextField";
import { Toggle } from "../components/Toggle";
import { useLiveEvent } from "../live/LiveProvider";
import { clock } from "../live/usePlayback";
import { type SearchChanges, SongSearch } from "../search/SongSearch";
import lib from "./Library.module.css";
import styles from "./Page.module.css";
import { describe, usePlaylistPlayer } from "./PlaylistsPage";

export function PlaylistPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [playlist, setPlaylist] = useState<PlaylistDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"add" | "rename" | "delete" | null>(null);
  const shuffleId = useId();

  const load = useCallback(() => {
    api<PlaylistDetail>("GET", `/playlists/${id}`)
      .then(setPlaylist)
      .catch((caught) => setError(errorText(caught)));
  }, [id]);
  useEffect(load, [load]);
  useLiveEvent("queue", load);
  const { play, takeOff, toast } = usePlaylistPlayer(load);

  const change = async (changes: { name?: string; shuffle?: boolean }) => {
    setError(null);
    try {
      setPlaylist(await api<PlaylistDetail>("PATCH", `/playlists/${id}`, changes));
    } catch (caught) {
      setError(errorText(caught));
    }
  };

  const remove = async (trackId: string) => {
    try {
      setPlaylist(await api<PlaylistDetail>("DELETE", `/playlists/${id}/tracks/${trackId}`));
    } catch (caught) {
      setError(errorText(caught));
    }
  };

  const best = playlist?.kind === "best_voted";

  return (
    <div className={`${styles.page} ${styles.narrow}`}>
      <header className={styles.header}>
        <div className={styles.headerStart}>
          <Link to="/playlists" aria-label="Back to Playlists" className={styles.iconLink}>
            <Icon name="back" />
          </Link>
          <h1 className={styles.title}>{playlist?.name ?? "Playlist"}</h1>
        </div>
        <div className={styles.headerEnd}>
          {playlist && !best && (
            <Button variant="ghost" onClick={() => setDialog("rename")}>
              Rename
            </Button>
          )}
          <HelpLink />
        </div>
      </header>

      <FormError message={error} />

      {playlist && (
        <>
          <p className={styles.muted}>
            {describe(playlist)}
            {best && ". Requests join when they get enough thumbs up."}
          </p>

          <div className={lib.controls}>
            {playlist.playing ? (
              <>
                <span className={lib.onAir}>On air</span>
                <Button variant="secondary" onClick={takeOff}>
                  Take off
                </Button>
              </>
            ) : (
              <Button disabled={playlist.items.length === 0} onClick={() => play(playlist)}>
                <Icon name="play" size={16} />
                Play
              </Button>
            )}
            <span className={lib.shuffle}>
              <span id={shuffleId}>Shuffle</span>
              <Toggle
                checked={playlist.shuffle}
                onChange={(shuffle) => change({ shuffle })}
                labelledBy={shuffleId}
              />
            </span>
            {!best && (
              <Button variant="secondary" onClick={() => setDialog("add")}>
                <Icon name="plus" size={16} strokeWidth={2.6} />
                Add songs
              </Button>
            )}
          </div>

          {playlist.items.length === 0 ? (
            <div className={styles.empty}>
              <p className={styles.emptyText}>
                {best
                  ? "Nothing yet. Requests that get enough thumbs up appear here."
                  : "No songs yet. Use Add songs to find some."}
              </p>
            </div>
          ) : (
            <ol className={lib.tracks}>
              {playlist.items.map((item, index) => (
                <li key={item.id} className={lib.track}>
                  <span className={lib.number}>{index + 1}</span>
                  {item.art_url ? (
                    <img src={item.art_url} alt="" className={lib.art} />
                  ) : (
                    <span aria-hidden="true" className={lib.art} />
                  )}
                  <span className={lib.text}>
                    <span className={lib.name}>{item.title}</span>
                    <span className={lib.meta}>
                      {item.artists} · {clock(item.duration)}
                    </span>
                  </span>
                  {best && (
                    <span className={lib.upvotes} aria-label={`${item.upvotes} thumbs up`}>
                      <Icon name="thumbUp" size={14} filled />
                      {item.upvotes}
                    </span>
                  )}
                  <button
                    type="button"
                    aria-label={`Remove ${item.title} from ${playlist.name}`}
                    className={lib.remove}
                    onClick={() => remove(item.id)}
                  >
                    <Icon name="close" size={18} />
                  </button>
                </li>
              ))}
            </ol>
          )}

          {!best && (
            <Button variant="ghost" className={lib.delete} onClick={() => setDialog("delete")}>
              Delete this playlist
            </Button>
          )}

          <AddSongs
            open={dialog === "add"}
            onClose={() => setDialog(null)}
            playlist={playlist}
            onPlaylist={setPlaylist}
          />
          <Rename
            open={dialog === "rename"}
            onClose={() => setDialog(null)}
            name={playlist.name}
            onSave={async (name) => {
              await change({ name });
              setDialog(null);
            }}
          />
          <Dialog open={dialog === "delete"} onClose={() => setDialog(null)} title="Delete playlist?">
            <p className={styles.muted}>
              {playlist.name} and its {playlist.items.length} songs will be gone. This can't be
              undone.
            </p>
            <div className={lib.formButtons}>
              <Button variant="secondary" onClick={() => setDialog(null)}>
                Cancel
              </Button>
              <Button
                onClick={async () => {
                  try {
                    await api("DELETE", `/playlists/${playlist.id}`);
                    navigate("/playlists");
                  } catch (caught) {
                    setError(errorText(caught));
                    setDialog(null);
                  }
                }}
              >
                Delete
              </Button>
            </div>
          </Dialog>
        </>
      )}
      {toast}
    </div>
  );
}

type AddProps = {
  open: boolean;
  onClose: () => void;
  playlist: PlaylistDetail;
  onPlaylist: (playlist: PlaylistDetail) => void;
};

function AddSongs({ open, onClose, playlist, onPlaylist }: AddProps) {
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
    <Dialog open={open} onClose={close} title={`Add songs to ${playlist.name}`} tall>
      <SongSearch
        query={search.q}
        artist={search.artist}
        onChange={update}
        addTo={{ to: "playlist", playlist, onPlaylist }}
        autoFocus
      />
    </Dialog>
  );
}

type RenameProps = {
  open: boolean;
  onClose: () => void;
  name: string;
  onSave: (name: string) => Promise<void>;
};

function Rename({ open, onClose, name, onSave }: RenameProps) {
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSave(String(new FormData(event.currentTarget).get("name") ?? ""));
  };
  return (
    <Dialog open={open} onClose={onClose} title="Rename playlist">
      <form className={lib.form} onSubmit={submit}>
        <TextField label="Name" name="name" defaultValue={name} required maxLength={100} />
        <div className={lib.formButtons}>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit">Save</Button>
        </div>
      </form>
    </Dialog>
  );
}
