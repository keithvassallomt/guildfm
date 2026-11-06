import { useEffect } from "react";
import type { Note } from "../api";
import { useAuth } from "../auth/AuthProvider";
import { Button } from "../components/Button";
import { Dialog } from "../components/Dialog";
import { useWide } from "../components/useWide";
import { Markdown } from "../help/Markdown";
import { readable } from "../help/topics";
import styles from "./WhatsNew.module.css";

type Props = { notes: Note[]; onClose: () => void };

/** The notes, newest first, each as its reader can see it: a `::: needs x` part only for
 *  people who can x. Notes with nothing for this reader count as seen without showing. */
export default function NewsDialog({ notes, onClose }: Props) {
  const { me, can } = useAuth();
  const size = useWide() ? "desktop" : "phone";
  const shown = notes
    .map((note) => ({ ...note, text: readable(note.text, can, size).trim() }))
    .filter((note) => note.text);
  const nothing = shown.length === 0;

  useEffect(() => {
    if (nothing) onClose();
  }, [nothing, onClose]);

  if (nothing || !me) return null;
  return (
    <Dialog open onClose={onClose} title="What's new in GuildFM">
      <div
        className={styles.notes}
        // Following a link into the help counts as having read it.
        onClick={(event) => (event.target as Element).closest("a") && onClose()}
      >
        {shown.map((note) => (
          <section key={note.version} className={styles.note}>
            <Markdown text={note.text} role={me.role} />
          </section>
        ))}
      </div>
      <Button block onClick={onClose}>
        Got it
      </Button>
    </Dialog>
  );
}
