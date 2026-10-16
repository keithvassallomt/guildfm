import { type FormEvent, type ReactNode, useEffect, useId, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import {
  type AnnounceMode,
  type Announcement,
  type AnnouncementsState,
  type Day,
  type PlaybackState,
  type Repeat,
  type RoomRef,
  api,
  errorText,
} from "../api";
import { Button, ButtonLink } from "../components/Button";
import { ChoiceCards } from "../components/ChoiceCards";
import { Dialog } from "../components/Dialog";
import { Icon } from "../components/Icon";
import { PreviewButton } from "../components/PreviewButton";
import { SegmentedControl } from "../components/SegmentedControl";
import { FormError } from "../components/TextField";
import { usePlayback } from "../live/usePlayback";
import a from "./Announcements.module.css";
import { DAYS, REPEATS, summarise } from "./announcementText";
import styles from "./Page.module.css";

const MAX_TEXT = 600;
const LIST = "/admin/announcements";

const MODES: { value: AnnounceMode; label: string; hint: string }[] = [
  {
    value: "after",
    label: "Wait for the song to finish",
    hint: "Plays between songs, then the music carries on.",
  },
  {
    value: "over",
    label: "Play over the music",
    hint: "The music goes quiet while it plays, then comes back up.",
  },
];

type Form = {
  text: string;
  rooms: RoomRef[]; // none chosen means every room
  now: boolean;
  mode: AnnounceMode;
  start_date: string;
  at: string;
  repeat: Repeat;
  days: Day[];
  ends_on: string;
};

const pad = (n: number) => String(n).padStart(2, "0");

/** Starts as "now"; scheduling suggests the next hour today. */
function blank(): Form {
  const next = new Date(Date.now() + 60 * 60 * 1000);
  return {
    text: "",
    rooms: [],
    now: true,
    mode: "after",
    start_date: `${next.getFullYear()}-${pad(next.getMonth() + 1)}-${pad(next.getDate())}`,
    at: `${pad(next.getHours())}:00`,
    repeat: "once",
    days: [],
    ends_on: "",
  };
}

function fromAnnouncement(item: Announcement): Form {
  return {
    text: item.text,
    rooms: item.rooms ?? [],
    now: false,
    mode: item.mode,
    start_date: item.start_date,
    at: item.at,
    repeat: item.repeat,
    days: item.days,
    ends_on: item.ends_on ?? "",
  };
}

/** The rooms on the network, plus any the announcement names that have gone. */
function roomChoices(playback: PlaybackState | null, chosen: RoomRef[]): RoomRef[] {
  const live = (playback?.rooms ?? []).map(({ uid, name }) => ({ uid, name }));
  const gone = chosen.filter((room) => !live.some((r) => r.uid === room.uid));
  return [...live, ...gone];
}

/** New announcement, or editing a scheduled one (/admin/announcements/:id). */
export function AnnouncementEditor() {
  const { id } = useParams();
  const editing = id !== undefined;
  const navigate = useNavigate();
  const { state: playback } = usePlayback();
  const [form, setForm] = useState<Form | null>(editing ? null : blank);
  const [voice, setVoice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    api<AnnouncementsState>("GET", "/announcements")
      .then((data) => setVoice(data.voice))
      .catch(() => {});
    if (id !== undefined) {
      api<Announcement>("GET", `/announcements/${id}`)
        .then((item) => setForm(fromAnnouncement(item)))
        .catch((caught) => setError(errorText(caught)));
    }
  }, [id]);

  const change = (changes: Partial<Form>) =>
    setForm((current) => current && { ...current, ...changes });

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!form) return;
    setBusy(true);
    setError(null);
    const rooms = form.rooms.length > 0 ? form.rooms : null;
    const where = rooms ? rooms.map((room) => room.name).join(", ") : "all rooms";
    try {
      let said: string;
      if (form.now) {
        const { waits } = await api<{ waits: boolean }>("POST", "/announcements/now", {
          text: form.text,
          rooms,
          mode: form.mode,
        });
        said = waits ? `Plays in ${where} after this song.` : `Playing now in ${where}.`;
      } else {
        const body = {
          text: form.text,
          rooms,
          mode: form.mode,
          start_date: form.start_date,
          at: form.at,
          repeat: form.repeat,
          days: form.days,
          ends_on: form.repeat !== "once" && form.ends_on ? form.ends_on : null,
        };
        await api(editing ? "PUT" : "POST", editing ? `/announcements/${id}` : "/announcements", body);
        said = editing ? "Saved." : "Scheduled.";
      }
      navigate(LIST, { state: { said } });
    } catch (caught) {
      setError(errorText(caught));
      setBusy(false);
    }
  };

  const remove = async () => {
    try {
      await api("DELETE", `/announcements/${id}`);
      navigate(LIST, { state: { said: "Deleted." } });
    } catch (caught) {
      setDeleting(false);
      setError(errorText(caught));
    }
  };

  const title = editing ? "Edit announcement" : "New announcement";
  const pickedDays = form?.repeat !== "days" || form.days.length > 0;
  const ready = !!form && form.text.trim() !== "" && (form.now || (!!form.start_date && !!form.at && pickedDays));

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerStart}>
          <Link to={LIST} aria-label="Back to Announcements" className={styles.iconLink}>
            <Icon name="back" />
          </Link>
          <h1 className={styles.title}>{title}</h1>
        </div>
      </header>

      {!form && <FormError message={error} />}
      {form && (
        <form className={styles.columns} onSubmit={submit}>
          <div className={styles.stack}>
            <Message form={form} voice={voice} onChange={(text) => change({ text })} onError={setError} />
            <Rooms
              choices={roomChoices(playback, form.rooms)}
              chosen={form.rooms}
              onChange={(rooms) => change({ rooms })}
            />
          </div>

          <div className={styles.stack}>
            <Group legend="When">
              {!editing && (
                <SegmentedControl
                  label="When"
                  options={[
                    { value: "now", label: "Now" },
                    { value: "later", label: "Schedule" },
                  ]}
                  value={form.now ? "now" : "later"}
                  onChange={(when) => change({ now: when === "now" })}
                />
              )}
              {!form.now && (
                <div className={a.pair}>
                  <label className={a.field}>
                    <span className={a.fieldLabel}>Starting</span>
                    <input
                      type="date"
                      required
                      value={form.start_date}
                      onChange={(event) => change({ start_date: event.target.value })}
                      className={a.input}
                    />
                  </label>
                  <label className={a.field}>
                    <span className={a.fieldLabel}>At</span>
                    <input
                      type="time"
                      required
                      value={form.at}
                      onChange={(event) => change({ at: event.target.value })}
                      className={a.input}
                    />
                  </label>
                </div>
              )}
            </Group>

            <Group legend="If music is playing">
              <ChoiceCards
                label="If music is playing"
                choices={MODES}
                value={form.mode}
                onChange={(mode) => change({ mode })}
              />
            </Group>

            {!form.now && <Repeats form={form} onChange={change} />}

            <p className={a.summary}>
              {summarise({ ...form, rooms: form.rooms.map((room) => room.name) })}
            </p>
            <FormError message={error} />
            <div className={a.formActions}>
              <ButtonLink variant="secondary" block to={LIST}>
                Cancel
              </ButtonLink>
              <Button type="submit" block disabled={busy || !ready}>
                {form.now ? "Play now" : editing ? "Save" : "Schedule"}
              </Button>
            </div>
            {editing && (
              <Button variant="ghost" className={a.delete} onClick={() => setDeleting(true)}>
                Delete announcement
              </Button>
            )}
          </div>
        </form>
      )}

      <Dialog open={deleting} onClose={() => setDeleting(false)} title="Delete this announcement?">
        <p className={styles.muted}>It won't play again. What's already played stays in the log.</p>
        <div className={a.formActions}>
          <Button variant="secondary" block onClick={() => setDeleting(false)}>
            Keep it
          </Button>
          <Button block onClick={remove}>
            Delete
          </Button>
        </div>
      </Dialog>
    </div>
  );
}

function Group({ legend, children }: { legend: string; children: ReactNode }) {
  return (
    <fieldset className={a.group}>
      <legend className={a.legend}>{legend}</legend>
      {children}
    </fieldset>
  );
}

type MessageProps = {
  form: Form;
  voice: string | null;
  onChange: (text: string) => void;
  onError: (message: string | null) => void;
};

function Message({ form, voice, onChange, onError }: MessageProps) {
  const id = useId();
  const name = voice ? voice.charAt(0).toUpperCase() + voice.slice(1) : null;
  return (
    <div className={a.group}>
      <label htmlFor={id} className={a.legend}>
        What should it say?
      </label>
      <textarea
        id={id}
        rows={4}
        required
        maxLength={MAX_TEXT}
        value={form.text}
        placeholder="Lunch is ready in the kitchen. Come and get it while it's hot."
        onChange={(event) => onChange(event.target.value)}
        className={a.textarea}
      />
      <div className={a.voiceRow}>
        <span className={a.voiceNote}>
          {name ? (
            <>
              Read out in <strong>{name}</strong>, the announcement voice from Settings.
            </>
          ) : (
            "Read out in the announcement voice from Settings."
          )}
        </span>
        <PreviewButton text={form.text} onError={onError} />
      </div>
    </div>
  );
}

type RoomsProps = { choices: RoomRef[]; chosen: RoomRef[]; onChange: (rooms: RoomRef[]) => void };

function Rooms({ choices, chosen, onChange }: RoomsProps) {
  const picked = (room: RoomRef) => chosen.some((r) => r.uid === room.uid);
  const flip = (room: RoomRef) =>
    onChange(picked(room) ? chosen.filter((r) => r.uid !== room.uid) : [...chosen, room]);

  return (
    <Group legend="Where">
      <div className={a.chipRow}>
        <button
          type="button"
          aria-pressed={chosen.length === 0}
          className={a.pick}
          onClick={() => onChange([])}
        >
          All rooms
        </button>
        {choices.map((room) => (
          <button
            key={room.uid}
            type="button"
            aria-pressed={picked(room)}
            className={a.pick}
            onClick={() => flip(room)}
          >
            {room.name}
          </button>
        ))}
      </div>
      <p className={a.hint}>Rooms playing the TV are left out.</p>
    </Group>
  );
}

function Repeats({ form, onChange }: { form: Form; onChange: (changes: Partial<Form>) => void }) {
  const endsId = useId();
  const flipDay = (day: Day) =>
    onChange({
      days: form.days.includes(day) ? form.days.filter((d) => d !== day) : [...form.days, day],
    });

  return (
    <Group legend="Repeat">
      <div role="radiogroup" aria-label="Repeat" className={a.chipRow}>
        {REPEATS.map((repeat) => (
          <button
            key={repeat.value}
            type="button"
            role="radio"
            aria-checked={form.repeat === repeat.value}
            className={a.pick}
            onClick={() => onChange({ repeat: repeat.value })}
          >
            {repeat.label}
          </button>
        ))}
      </div>
      {form.repeat === "days" && (
        <div className={a.days}>
          {DAYS.map(({ day, letter, long }) => (
            <button
              key={day}
              type="button"
              aria-label={long}
              aria-pressed={form.days.includes(day)}
              className={`${a.pick} ${a.day}`}
              onClick={() => flipDay(day)}
            >
              {letter}
            </button>
          ))}
        </div>
      )}
      {form.repeat === "hourly" && (
        <p className={a.hint}>Plays every hour at the same minutes past, only in playback hours.</p>
      )}
      {form.repeat !== "once" && (
        <div className={a.ends}>
          <label htmlFor={endsId} className={a.fieldLabel}>
            Ends
          </label>
          <input
            id={endsId}
            type="date"
            value={form.ends_on}
            min={form.start_date}
            onChange={(event) => onChange({ ends_on: event.target.value })}
            className={a.input}
          />
          {form.ends_on && (
            <Button variant="ghost" onClick={() => onChange({ ends_on: "" })}>
              Never
            </Button>
          )}
        </div>
      )}
      {form.repeat !== "once" && !form.ends_on && <p className={a.hint}>Keeps going until you stop it.</p>}
    </Group>
  );
}
