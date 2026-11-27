import { type ReactNode, useCallback, useEffect, useId, useState } from "react";
import { Link } from "react-router";
import {
  api,
  errorText,
  type Hours,
  type PlaybackState,
  type SettingsState,
  type SettingsValues,
  VOICES,
} from "../api";
import { Button } from "../components/Button";
import { ChoiceCards } from "../components/ChoiceCards";
import { HelpLink } from "../components/HelpLink";
import { Icon } from "../components/Icon";
import { SegmentedControl } from "../components/SegmentedControl";
import { SpotifyConnection } from "../components/SpotifyConnection";
import { Stepper } from "../components/Stepper";
import { FormError, TextField } from "../components/TextField";
import { Toggle } from "../components/Toggle";
import { isEleven, useVoices, voiceName } from "../components/useVoices";
import { VoicePreview } from "../components/VoicePreview";
import { opensAgain, playingUntil } from "../live/status";
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

const KIOSK_LOOKS = [
  { value: "dark" as const, label: "Dark" },
  { value: "light" as const, label: "Light" },
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
    hint: "Switches to the station chosen below. With none chosen, AI picks.",
  },
  {
    value: "ai_pick" as const,
    label: "Let the AI pick the next song",
    hint: "The AI picks station: songs that follow on from what has been playing.",
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
  const voices = useVoices();
  const elevenlabs = voices?.elevenlabs ?? [];

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerStart}>
          <Link to="/admin" aria-label="Back to Admin" className={styles.iconLink}>
            <Icon name="back" />
          </Link>
          <h1 className={styles.title}>Settings</h1>
        </div>
        <div className={styles.headerEnd}>
          <span role="status" className={s.saved}>
            {saved === "saving" ? "Saving..." : saved === "saved" ? "Saved" : "Saves as you go"}
          </span>
          <HelpLink />
        </div>
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
                hint="Off by default: they're hidden from search, refused as requests, and left out of albums and AI stations."
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
              {values.queue_runs_out === "default_station" && (
                <label className={s.field}>
                  <span className={s.fieldLabel}>Default AI station</span>
                  <select
                    value={values.default_station ?? 0}
                    onChange={(event) => save({ default_station: Number(event.target.value) })}
                    className={s.select}
                  >
                    <option value={0}>None: AI picks instead</option>
                    {settings.stations.map((station) => (
                      <option key={station.id} value={station.id}>
                        {station.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <p className={styles.muted}>
                This is for when a playlist plays to the end, or nothing was chosen. Choosing
                Requests only on Now Playing means nothing takes over.
              </p>
            </Section>

            <Section title="Kiosk">
              <Row
                label="Places"
                hint="Songs the kiosk can add before it takes a break. One that plays gives its place back."
              >
                <Stepper
                  label="Kiosk places"
                  value={values.kiosk_places}
                  min={1}
                  max={30}
                  onChange={(kiosk_places) => save({ kiosk_places })}
                />
              </Row>
              <Row
                label="Break"
                hint="Minutes. Once its places are all taken, the kiosk can't add or vote for this long."
              >
                <Stepper
                  label="Kiosk break"
                  value={values.kiosk_break_minutes}
                  min={1}
                  max={30}
                  onChange={(kiosk_break_minutes) => save({ kiosk_break_minutes })}
                />
              </Row>
              <div className={s.stacked}>
                <RowText label="Look" hint="How the kiosk's screen looks." />
                <SegmentedControl
                  label="Kiosk look"
                  options={KIOSK_LOOKS}
                  value={values.kiosk_theme}
                  onChange={(kiosk_theme) => save({ kiosk_theme })}
                />
              </div>
              <p className={styles.muted}>
                The kiosk is the touchscreen in the office. Give an account the Kiosk role on the
                Users page, then sign in with it on the kiosk.
              </p>
            </Section>
          </div>

          <div className={styles.stack}>
            <Section title="Playback hours">
              <p className={settings.hours.open ? s.open : styles.muted}>
                {settings.hours.open
                  ? "Open now."
                  : ["Closed.", playingUntil(settings.hours), opensAgain(settings.hours)]
                      .filter(Boolean)
                      .join(" ")}
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
              <Row
                label="After-hours play"
                hint="Hours. Pressing Play outside the hours plays for this long, then it stops again."
              >
                <Stepper
                  label="After-hours play"
                  value={values.after_hours_play_hours}
                  min={1}
                  max={12}
                  onChange={(after_hours_play_hours) => save({ after_hours_play_hours })}
                />
              </Row>
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
                  <optgroup label="OpenAI">
                    {(voices?.openai ?? VOICES).map((voice) => (
                      <option key={voice} value={voice}>
                        {capitalise(voice)}
                      </option>
                    ))}
                  </optgroup>
                  {(elevenlabs.length > 0 || isEleven(values.announcement_voice)) && (
                    <optgroup label="ElevenLabs">
                      {elevenlabs.map((voice) => (
                        <option key={voice.id} value={voice.id}>
                          {voice.name}
                        </option>
                      ))}
                      {/* Still loading, or gone from the account. */}
                      {isEleven(values.announcement_voice) &&
                        !elevenlabs.some((voice) => voice.id === values.announcement_voice) && (
                          <option value={values.announcement_voice}>
                            {voiceName(values.announcement_voice, voices)}
                          </option>
                        )}
                    </optgroup>
                  )}
                </select>
                <span className={styles.muted}>
                  {isEleven(values.announcement_voice)
                    ? "An ElevenLabs voice. Announcements can act it out with tags like [excited] or [whispers]."
                    : "Marin and Cedar sound the most natural."}
                  {voices && !voices.elevenlabs_ready
                    ? " Add ELEVENLABS_API_KEY to .env to use your ElevenLabs voices too."
                    : ""}
                </span>
              </label>
              <VoicePreview voice={values.announcement_voice} />
            </Section>

            <OfficeLocation place={values.office_location} onChange={setSettings} />
            <SpotifyConnection />
            <SonosStatus />
            <MonitorMode />
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

type Place = SettingsValues["office_location"];

/** Where the office is, so people whose address isn't the office's (iPhones with iCloud Private
 * Relay, say) can confirm they're in it. It's set from this browser's own location, so it doesn't
 * go through the settings' save. */
function OfficeLocation({ place, onChange }: { place: Place; onChange: (s: SettingsState) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const change = async (method: "PUT" | "DELETE", body?: object) => {
    try {
      onChange(await api<SettingsState>(method, "/settings/office-location", body));
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  };

  const useHere = () => {
    if (!navigator.geolocation) {
      setError("This browser can't share its location.");
      return;
    }
    setBusy(true);
    setError(null);
    navigator.geolocation.getCurrentPosition(
      ({ coords }) =>
        change("PUT", {
          latitude: coords.latitude,
          longitude: coords.longitude,
          accuracy: coords.accuracy,
        }),
      (failure) => {
        setBusy(false);
        setError(
          failure.code === failure.PERMISSION_DENIED
            ? "This browser isn't allowed to share your location. Allow it for this site and try again."
            : "This browser couldn't work out where you are. Try again.",
        );
      },
      { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 },
    );
  };

  const remove = () => {
    setBusy(true);
    setError(null);
    change("DELETE");
  };

  const map =
    place &&
    `https://www.openstreetmap.org/?mlat=${place.latitude}&mlon=${place.longitude}#map=18/${place.latitude}/${place.longitude}`;

  return (
    <Section title="Office location">
      <p className={styles.muted}>
        Someone in the office whose address GuildFM can't see, such as an iPhone with iCloud
        Private Relay, can confirm their location instead, within 150 m of here. Set it while
        you're in the office.
      </p>
      <p className={styles.muted}>
        {place && map ? (
          <>
            Set to {place.latitude.toFixed(5)}, {place.longitude.toFixed(5)}.{" "}
            <a href={map} target="_blank" rel="noreferrer" className={s.link}>
              Show on a map
            </a>
          </>
        ) : (
          "Not set, so nobody can get in by their location."
        )}
      </p>
      <div className={s.buttons}>
        <Button variant={place ? "secondary" : "primary"} onClick={useHere} disabled={busy}>
          {busy ? "Finding you..." : "Use where I am now"}
        </Button>
        {place && (
          <Button variant="ghost" onClick={remove} disabled={busy}>
            Remove
          </Button>
        )}
      </div>
      <FormError message={error} />
    </Section>
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
                : state.monitor
                  ? "Not in use while monitor mode is on."
                  : state.status === "offline"
                  ? (state.error ?? "Can't reach the speakers.")
                  : `${state.rooms.length} speakers on the office network, led by ${state.coordinator}`}
            </span>
          </span>
          {state && (
            <span className={state.status === "offline" ? s.badgeWarn : s.badge}>
              {state.monitor ? "Not in use" : state.status === "offline" ? "Offline" : "Online"}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}

/** Monitor mode: GuildFM plays in browsers instead of on the speakers. It takes effect at once,
 * so it doesn't go through the settings' save. */
function MonitorMode() {
  const { state, apply } = usePlayback();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const id = useId();

  const turn = async (on: boolean) => {
    setBusy(true);
    setError(null);
    try {
      apply(await api<PlaybackState>("PUT", "/playback/monitor", { on }));
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Monitor mode">
      <div className={s.row}>
        <RowText
          id={id}
          label="Play in a browser instead"
          hint="Try things out without the office hearing: GuildFM plays in your browser rather than on the Sonos speakers."
        />
        <Toggle
          checked={state?.monitor ?? false}
          onChange={turn}
          labelledBy={id}
          disabled={!state || busy}
        />
      </div>
      <p className={styles.muted}>
        Turning it on stops the music on the Sonos speakers, and GuildFM waits for Play. Songs
        become beeps, each as long as the real song; the DJ, jingles and announcements play for
        real. Press Listen here, at the top of any page, to hear it in that browser. Turning it
        off goes back to the speakers, again waiting for Play.
      </p>
      <FormError message={error} />
    </Section>
  );
}
