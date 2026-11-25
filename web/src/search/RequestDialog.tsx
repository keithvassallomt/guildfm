import { useState } from "react";
import type { QueueState } from "../api";
import { Dialog } from "../components/Dialog";
import { type SearchChanges, SongSearch } from "./SongSearch";

type Props = {
  open: boolean;
  onClose: () => void;
  queue: QueueState | null;
  onQueue: (queue: QueueState) => void;
};

/** Search and request without leaving the page, from Now Playing or the Queue. Each time it
 *  opens, it starts afresh. */
export function RequestDialog({ open, onClose, queue, onQueue }: Props) {
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
