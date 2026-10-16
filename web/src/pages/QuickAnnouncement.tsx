import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { type AnnounceMode, type AnnouncementsState, api, errorText } from "../api";
import { Button } from "../components/Button";
import { Dialog } from "../components/Dialog";
import { EmotionPicker } from "../components/EmotionPicker";
import { PreviewButton } from "../components/PreviewButton";
import { SegmentedControl } from "../components/SegmentedControl";
import { FormError } from "../components/TextField";
import { isEleven, useVoices, voiceName } from "../components/useVoices";
import styles from "./Page.module.css";
import q from "./QuickAnnouncement.module.css";

type Props = { open: boolean; onClose: () => void; onSent: (message: string) => void };

/** A one-off announcement in every room, straight from Now Playing. Scheduling and choosing
 * rooms are on the Announcements page. */
export function QuickAnnouncement({ open, onClose, onSent }: Props) {
  const navigate = useNavigate();
  const textId = useId();
  const [text, setText] = useState("");
  const [mode, setMode] = useState<AnnounceMode>("after");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);
  const voices = useVoices();
  // The announcement voice from Settings, read each time it opens, in case it changed.
  const [voice, setVoice] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    api<AnnouncementsState>("GET", "/announcements")
      .then((data) => setVoice(data.voice))
      .catch(() => {});
  }, [open]);
  const emotions = !!voice && isEleven(voice);

  const send = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { waits } = await api<{ waits: boolean }>("POST", "/announcements/now", {
        text,
        rooms: null,
        mode,
      });
      onSent(waits ? "Plays in every room after this song." : "Playing now in every room.");
      setText("");
      onClose();
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="Quick announcement">
      <form className={q.form} onSubmit={send}>
        <label htmlFor={textId} className={q.label}>
          What should it say?
        </label>
        <textarea
          ref={box}
          id={textId}
          rows={3}
          maxLength={600}
          value={text}
          placeholder="Lunch is here. Come and get it while it's hot."
          onChange={(event) => setText(event.target.value)}
          className={q.textarea}
        />
        <div className={q.tools}>
          {emotions && (
            <EmotionPicker
              className={q.emotion}
              textarea={box}
              text={text}
              maxLength={600}
              onText={setText}
            />
          )}
          <PreviewButton text={text} onError={setError} />
        </div>
        <SegmentedControl
          label="When"
          options={[
            { value: "after", label: "After this song" },
            { value: "over", label: "Over the music" },
          ]}
          value={mode}
          onChange={setMode}
        />
        <p className={styles.muted}>
          {voice ? `Read out in ${voiceName(voice, voices)}. ` : ""}
          Plays once, in every room.{" "}
          <button
            type="button"
            className={q.more}
            onClick={() => navigate("/admin/announcements/new", { state: { text } })}
          >
            Pick rooms or schedule it
          </button>
        </p>
        <FormError message={error} />
        <div className={q.buttons}>
          <Button variant="secondary" block onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" block disabled={busy || !text.trim()}>
            Play now
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
