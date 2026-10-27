import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { api, errorText, type Playlist, type PlaylistDetail } from "../api";
import { Button } from "../components/Button";
import { Dialog } from "../components/Dialog";
import { HelpLink } from "../components/HelpLink";
import { Icon } from "../components/Icon";
import { FormError, TextField } from "../components/TextField";
import { useToast } from "../components/Toast";
import { useLiveEvent } from "../live/LiveProvider";
import lib from "./Library.module.css";
import { Covers } from "./NowSources";
import styles from "./Page.module.css";

export function describe(playlist: Playlist): string {
  const songs = `${playlist.tracks} ${playlist.tracks === 1 ? "song" : "songs"}`;
  const how =
    playlist.kind === "best_voted"
      ? "picked by the votes"
      : playlist.kind === "imported"
        ? "imported from Spotify"
        : playlist.made_by
          ? `made by ${playlist.made_by}`
          : "made in GuildFM";
  return `${songs} · ${how}${playlist.shuffle ? " · shuffled" : ""}`;
}

/** Puts a playlist on, or takes the playing one off. Shared with the playlist screen. */
export function usePlaylistPlayer(onDone: () => void) {
  const { show, toast } = useToast();
  const play = async (playlist: Playlist) => {
    try {
      await api("POST", `/playlists/${playlist.id}/play`);
      show(`${playlist.name} is on from the next song. Requests still play first.`);
    } catch (caught) {
      show(errorText(caught));
    }
    onDone();
  };
  const takeOff = async () => {
    try {
      await api("DELETE", "/source");
    } catch (caught) {
      show(errorText(caught));
    }
    onDone();
  };
  return { play, takeOff, toast };
}

/** The playlists: putting one on, and making or importing new ones. */
export function PlaylistsPage() {
  const [playlists, setPlaylists] = useState<Playlist[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"new" | "import" | null>(null);

  const load = useCallback(() => {
    api<Playlist[]>("GET", "/playlists")
      .then(setPlaylists)
      .catch((caught) => setError(errorText(caught)));
  }, []);
  useEffect(load, [load]);
  // The playing playlist can change from elsewhere, so follow the queue's changes.
  useLiveEvent("queue", load);
  const { play, takeOff, toast } = usePlaylistPlayer(load);

  const playing = playlists?.find((playlist) => playlist.playing);

  return (
    <div className={`${styles.page} ${styles.narrow}`}>
      <header className={styles.header}>
        <h1 className={styles.title}>Playlists</h1>
        <HelpLink />
      </header>

      {playing && (
        <div className={lib.playing} role="status">
          <Icon name="queue" size={18} />
          <span className={lib.playingText}>
            Playing from <strong>{playing.name}</strong>. Requests always play first.
          </span>
          <Button variant="secondary" onClick={takeOff}>
            Take off
          </Button>
        </div>
      )}

      <FormError message={error} />
      {playlists && (
        <ul className={lib.list}>
          {playlists.map((playlist) => (
            <li key={playlist.id} className={lib.item}>
              <Link to={`/playlists/${playlist.id}`} className={lib.link}>
                <span
                  aria-hidden="true"
                  className={`${lib.tile} ${playlist.kind === "best_voted" ? lib.best : ""}`}
                >
                  {playlist.covers.length > 0 ? (
                    <Covers urls={playlist.covers} />
                  ) : playlist.kind === "best_voted" ? (
                    <Icon name="thumbUp" size={22} filled />
                  ) : (
                    playlist.name.charAt(0).toUpperCase()
                  )}
                </span>
                <span className={lib.text}>
                  <span className={lib.name}>{playlist.name}</span>
                  <span className={lib.meta}>{describe(playlist)}</span>
                </span>
              </Link>
              {playlist.playing ? (
                <span className={lib.onAir}>On air</span>
              ) : (
                <button
                  type="button"
                  aria-label={`Play ${playlist.name}`}
                  disabled={playlist.tracks === 0}
                  className={lib.play}
                  onClick={() => play(playlist)}
                >
                  <Icon name="play" size={18} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className={lib.actions}>
        <Button variant="secondary" onClick={() => setDialog("new")}>
          <Icon name="plus" size={16} strokeWidth={2.6} />
          New playlist
        </Button>
        <Button onClick={() => setDialog("import")}>Import from Spotify</Button>
      </div>

      <NewPlaylist open={dialog === "new"} onClose={() => setDialog(null)} />
      <ImportPlaylist open={dialog === "import"} onClose={() => setDialog(null)} />
      {toast}
    </div>
  );
}

function NewPlaylist({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("name") ?? "");
    setBusy(true);
    setError(null);
    try {
      const made = await api<PlaylistDetail>("POST", "/playlists", { name });
      navigate(`/playlists/${made.id}`);
    } catch (caught) {
      setError(errorText(caught));
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="New playlist">
      <form className={lib.form} onSubmit={submit}>
        <TextField label="Name" name="name" required maxLength={100} autoComplete="off" />
        <FormError message={error} />
        <div className={lib.formButtons}>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy}>
            Create
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function ImportPlaylist({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const link = String(new FormData(event.currentTarget).get("link") ?? "");
    setBusy(true);
    setError(null);
    try {
      const imported = await api<PlaylistDetail>("POST", "/playlists/import", { link });
      navigate(`/playlists/${imported.id}`);
    } catch (caught) {
      setError(errorText(caught));
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="Import from Spotify">
      <form className={lib.form} onSubmit={submit}>
        <TextField
          label="Spotify playlist or album link"
          name="link"
          required
          autoComplete="off"
          placeholder="https://open.spotify.com/..."
          hint="In Spotify: the playlist's or album's ⋯ menu, then Share, then Copy link."
        />
        <p className={styles.muted}>
          Any album can be imported, as a playlist named after it. Playlists can only be imported
          if the connected Spotify account owns or collaborates on them. For anyone else's, copy
          it into one of that account's playlists in Spotify first.
        </p>
        <FormError message={error} />
        <div className={lib.formButtons}>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy}>
            {busy ? "Importing..." : "Import"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
