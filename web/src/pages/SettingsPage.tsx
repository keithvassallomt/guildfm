import { type ReactNode, useCallback, useEffect, useId, useState } from "react";
import { Link } from "react-router";
import { api, errorText, type Hours, type SettingsState, type SettingsValues } from "../api";
import { ChoiceCards } from "../components/ChoiceCards";
import { Icon } from "../components/Icon";
import { SegmentedControl } from "../components/SegmentedControl";
import { SpotifyConnection } from "../components/SpotifyConnection";
import { Stepper } from "../components/Stepper";
import { FormError, TextField } from "../components/TextField";
import { Toggle } from "../components/Toggle";
import { opensAgain } from "../live/status";
import { usePlayback } from "../live/usePlayback";
import styles from "./Page.module.css";
import s from "./SettingsPage.module.css";

type Day = keyof SettingsValues["schedule"];

const DAYS: [Day, string][] = [
  ["mon", "Monday"],
  ["tue", "Tuesday"],
  ["wed", "Wednesday"],
  ["thu", "Thursday"],
  ["fri", "Friday"],
  ["sat", "Saturday"],
  ["sun", "Sunday"],
];

const RECENTLY = [
  { value: "12", label: "12 h" },
  { value: "24", label: "24 h" },
  { value: "48", label: "48 h" },
  { value: "168", label: "7 days" },
];

const RUNS_OUT = [
  {
    value: "restart_playlist" as const,
    label: "Restart the current playlist",
    hint: "If no playlist is playing, the AI picks instead.",
  },
  {
    value: "default_station" as const,
    label: "Play the default AI station",
    hint: "Switches to the station chosen as the default.",
  },
  {
    value: "ai_pick" as const,
    label: "Let the AI pick the next song",
    hint: "Something that fits what has been playing.",
  },
];

const capitalise = (word: string) => word.charAt(0).toUpperCase() + word.slice(1);

export function SettingsPage() {
  const [settings, setSettings] = useState<SettingsState | null>(null);
  const [saved, setSaved] = useState<"saving" | "saved" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<SettingsState>("GET", "/settings")
      .then(setSettings)
      .catch((caught) => setError(errorText(caught)));
  }, []);
  useEffect(load, [load]);

  /** Save a change straight away, showing it before the server confirms. */
  const save = async (changes: Partial<SettingsValues>) => {
    setSettings((current) => current && { ...current, values: { ...current.values, ...changes } });
    setSaved("saving");
    setError(null);
    try {
      setSettings(await api<SettingsState>("PATCH", "/settings", changes));
      setSaved("saved");
    } catch (caught) {
      setError(errorText(caught));
      setSaved(null);
      load();
    }
  };

  const values = settings?.values;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerStart}>
          <Link to="/admin" aria-label="Back to Admin" className={styles.iconLink}>
            <Icon name="back" />
          </Link>
          <h1 className={styles.title}>Settings</h1>
        </div>
        <span role="status" className={s.saved}>
          {saved === "saving" ? "Saving..." : saved === "saved" ? "Saved" : "Saves as you go"}
        </span>
      </header>

      <FormError message={error} />

      {settings && values && (
        <div className={styles.columns}>
          <div className={styles.stack}>
            <Section title="Queue and voting">
              <Row label="Requests per person" hint="How many songs one person can have in the queue at once.">
                <Stepper
                  label="Requests per person"
                  value={values.request_cap}
                  min={1}
                  max={50}
                  onChange={(request_cap) => save({ request_cap })}
                />
              </Row>
              <Row label="Remove at score" hint="A request is taken out when its votes add up to this.">
                <Stepper
                  label="Remove at score"
                  value={values.downvote_threshold}
                  min={-50}
                  max={-1}
                  onChange={(downvote_threshold) => save({ downvote_threshold })}
                />
              </Row>
              <div className={s.stacked}>
                <RowText
                  label="Recently played means"
                  hint="Songs played within this time get a badge. They can still be requested."
                />
                <SegmentedControl
                  label="Recently played means"
                  options={RECENTLY}
                  value={String(values.recently_played_hours)}
                  onChange={(hours) => save({ recently_played_hours: Number(hours) })}
                />
              </div>
              <ToggleRow
                label="Allow explicit tracks"
                hint="Turn off to hide them from search and refuse requests for them."
                checked={values.allow_explicit}
                onChange={(allow_explicit) => save({ allow_explicit })}
              />
            </Section>

            <Section title="Best Voted playlist">
              <Row label="Upvotes to get in" hint="A track joins once it has more than this many.">
                <Stepper
                  label="Upvotes to get in"
                  value={values.best_voted_min_upvotes}
                  min={1}
                  max={100}
                  onChange={(best_voted_min_upvotes) => save({ best_voted_min_upvotes })}
                />
              </Row>
              <Row label="Playlist size" hint="The most tracks it holds.">
                <Stepper
                  label="Playlist size"
                  value={values.best_voted_size}
                  min={10}
                  max={500}
                  step={10}
                  onChange={(best_voted_size) => save({ best_voted_size })}
                />
              </Row>
              <p className={styles.muted}>
                When it's full, the track with the fewest upvotes drops out; on a tie, the oldest.
              </p>
            </Section>

            <Section title="When the queue runs out">
              <ChoiceCards
                label="When the queue runs out"
                choices={RUNS_OUT}
                value={values.queue_runs_out}
                onChange={(queue_runs_out) => save({ queue_runs_out })}
              />
              <p className={styles.muted}>
                AI radio arrives in stage 10. Until then, both AI choices stop the music once the
                queue and any playlist run out.
              </p>
            </Section>
          </div>

          <div className={styles.stack}>
            <Section title="Playback hours">
              <p className={settings.hours.open ? s.open : styles.muted}>
                {settings.hours.open ? "Open now." : `Closed. ${opensAgain(settings.hours)}`}
              </p>
              <ul className={s.days}>
                {DAYS.map(([day, name]) => (
                  <DayRow
                    key={day}
                    name={name}
                    hours={values.schedule[day]}
                    onChange={(hours) => save({ schedule: { ...values.schedule, [day]: hours } })}
                  />
                ))}
              </ul>
              <label className={s.field}>
                <span className={s.fieldLabel}>Time zone</span>
                <select
                  value={values.timezone}
                  onChange={(event) => save({ timezone: event.target.value })}
                  className={s.select}
                >
                  {settings.timezones.map((zone) => (
                    <option key={zone}>{zone}</option>
                  ))}
                </select>
              </label>
              <p className={styles.muted}>
                At opening time GuildFM starts by itself if there's anything to play. At closing
                time it stops everything.
              </p>
            </Section>

            <Section title="AI and voice">
              <SaveOnLeave
                label="Weather location"
                value={values.weather_location}
                hint="Used by stations with global awareness turned on."
                onSave={(weather_location) => save({ weather_location })}
              />
              <label className={s.field}>
                <span className={s.fieldLabel}>Announcement voice</span>
                <select
                  value={values.announcement_voice}
                  onChange={(event) => save({ announcement_voice: event.target.value })}
                  className={s.select}
                >
                  {settings.voices.map((voice) => (
                    <option key={voice} value={voice}>
                      {capitalise(voice)}
                    </option>
                  ))}
                </select>
                <span className={styles.muted}>
                  Marin and Cedar sound the most natural. Previews come with announcements in
                  stage 9.
                </span>
              </label>
            </Section>

            <SpotifyConnection />
            <SonosStatus />
          </div>
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();
  return (
    <section className={styles.section} aria-labelledby={id}>
      <h2 id={id} className={styles.sectionTitle}>
        {title}
      </h2>
      <div className={styles.card}>{children}</div>
    </section>
  );
}

function RowText({ label, hint, id }: { label: string; hint: string; id?: string }) {
  return (
    <span className={s.rowText}>
      <span id={id} className={s.rowLabel}>
        {label}
      </span>
      <span className={s.rowHint}>{hint}</span>
    </span>
  );
}

function Row({ label, hint, children }: { label: string; hint: string; children: ReactNode }) {
  return (
    <div className={s.row}>
      <RowText label={label} hint={hint} />
      {children}
    </div>
  );
}

type ToggleRowProps = {
  label: string;
  hint: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
};

function ToggleRow({ label, hint, checked, onChange }: ToggleRowProps) {
  const id = useId();
  return (
    <div className={s.row}>
      <RowText id={id} label={label} hint={hint} />
      <Toggle checked={checked} onChange={onChange} labelledBy={id} />
    </div>
  );
}

/** One day's playback hours. Times are saved when the field is left, not on every keystroke. */
function DayRow({ name, hours, onChange }: { name: string; hours: Hours; onChange: (h: Hours) => void }) {
  const id = useId();
  const [start, setStart] = useState(hours.start);
  const [end, setEnd] = useState(hours.end);
  useEffect(() => {
    setStart(hours.start);
    setEnd(hours.end);
  }, [hours.start, hours.end]);

  const commit = () => {
    if (start !== hours.start || end !== hours.end) onChange({ ...hours, start, end });
  };

  return (
    <li className={s.day}>
      <span id={id} className={s.dayName}>
        {name}
      </span>
      {hours.on ? (
        <span className={s.times}>
          <input
            type="time"
            aria-label={`${name} opens at`}
            value={start}
            onChange={(event) => setStart(event.target.value)}
            onBlur={commit}
            className={s.time}
          />
          <span aria-hidden="true">to</span>
          <input
            type="time"
            aria-label={`${name} closes at`}
            value={end}
            onChange={(event) => setEnd(event.target.value)}
            onBlur={commit}
            className={s.time}
          />
        </span>
      ) : (
        <span className={s.off}>Off all day</span>
      )}
      <Toggle checked={hours.on} onChange={(on) => onChange({ ...hours, on })} labelledBy={id} />
    </li>
  );
}

type SaveOnLeaveProps = { label: string; value: string; hint: string; onSave: (v: string) => void };

function SaveOnLeave({ label, value, hint, onSave }: SaveOnLeaveProps) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => draft.trim() && draft.trim() !== value && onSave(draft.trim());
  return (
    <TextField
      label={label}
      value={draft}
      hint={hint}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => event.key === "Enter" && commit()}
    />
  );
}

function SonosStatus() {
  const { state } = usePlayback();
  return (
    <section className={styles.section} aria-label="Sonos">
      <div className={styles.card}>
        <div className={s.sonos}>
          <Icon name="admin" />
          <span className={s.rowText}>
            <span className={s.rowLabel}>Sonos speakers</span>
            <span className={s.rowHint}>
              {!state
                ? "Checking..."
                : state.status === "offline"
                  ? (state.error ?? "Can't reach the speakers.")
                  : `${state.rooms.length} speakers on the office network, led by ${state.coordinator}`}
            </span>
          </span>
          {state && (
            <span className={state.status === "offline" ? s.badgeWarn : s.badge}>
              {state.status === "offline" ? "Offline" : "Online"}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}
