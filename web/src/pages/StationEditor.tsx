import { type FormEvent, type ReactNode, useEffect, useId, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api, type DJProfile, errorText, type Station, type StationFields, VOICES } from "../api";
import { Button, ButtonLink } from "../components/Button";
import { ChoiceCards } from "../components/ChoiceCards";
import { Dialog } from "../components/Dialog";
import { Icon } from "../components/Icon";
import { JingleList } from "../components/JingleList";
import { useLeaveGuard } from "../components/LeaveGuard";
import { PreviewButton } from "../components/PreviewButton";
import { SegmentedControl } from "../components/SegmentedControl";
import { StationCover } from "../components/StationCover";
import { FormError, TextField } from "../components/TextField";
import { Toggle } from "../components/Toggle";
import { isEleven, useVoices, voiceName } from "../components/useVoices";
import { listed } from "./announcementText";
import { HourPreview } from "./HourPreview";
import styles from "./Page.module.css";
import e from "./StationEditor.module.css";

const BACK = "/radio";

const BLANK: StationFields = {
  name: "",
  description: "",
  global_awareness: false,
  dj: false,
  dj_id: null,
  dj_name: "",
  personality: "",
  voice: "marin",
  talk_every: 3,
  talk_unit: "tracks",
  style: "commentary",
  announce_requests: true,
  jingles: true,
};

const STYLES = [
  {
    value: "announce" as const,
    label: "Just announce the songs",
    hint: "Short and simple: what was playing and what's next.",
  },
  {
    value: "commentary" as const,
    label: "Add commentary",
    hint: "Trivia, the weather, and the odd story about the song.",
  },
];

// Each with tags for an ElevenLabs voice, which acts them out.
const PHRASES = [
  {
    id: "intro",
    label: "Track intro",
    text: "That was Stevie Wonder. Next up, a bit of Aretha to keep things moving.",
    tagged: "That was Stevie Wonder. [excited] Next up, a bit of Aretha to keep things moving.",
  },
  {
    id: "request",
    label: "Request shout-out",
    text: "This one's for Priya, who asked for some Fleetwood Mac. Here's Dreams.",
    tagged: "[chuckles] This one's for Priya, who asked for some Fleetwood Mac. Here's Dreams.",
  },
  {
    id: "weather",
    label: "Weather check",
    text: "Grey skies out there this afternoon, so here's something to warm you up.",
    tagged: "[sighs] Grey skies out there this afternoon, so here's something to warm you up.",
  },
  { id: "custom", label: "Your own words", text: "", tagged: "" },
];

function fieldsOf(station: Station): StationFields {
  const fields = { ...BLANK };
  for (const key of Object.keys(BLANK) as (keyof StationFields)[]) {
    (fields as Record<string, unknown>)[key] = station[key];
  }
  return fields;
}

/** New AI station, or editing one (/radio/:id). */
export function StationEditor() {
  const { id } = useParams();
  const editing = id !== undefined;
  const navigate = useNavigate();
  const [form, setForm] = useState<StationFields | null>(editing ? null : BLANK);
  // The form as saved, to tell whether there are changes to lose.
  const [saved, setSaved] = useState<StationFields | null>(editing ? null : BLANK);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  // The form as it was when the hour preview was opened.
  const [previewing, setPreviewing] = useState<StationFields | null>(null);
  const [art, setArt] = useState<string | null>(null);

  useEffect(() => {
    if (id === undefined) return;
    api<Station>("GET", `/stations/${id}`)
      .then((station) => {
        setForm(fieldsOf(station));
        setSaved(fieldsOf(station));
        setArt(station.art_url);
      })
      .catch((caught) => setError(errorText(caught)));
  }, [id]);

  const change = (changes: Partial<StationFields>) =>
    setForm((current) => current && { ...current, ...changes });

  const dirty = !!form && !!saved && JSON.stringify(form) !== JSON.stringify(saved);
  const { allow, dialog: leaving } = useLeaveGuard(dirty);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!form) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await api<Station>(
        editing ? "PUT" : "POST",
        editing ? `/stations/${id}` : "/stations",
        form,
      );
      allow();
      navigate(BACK, { state: { said: editing ? "Saved." : `${saved.name} is ready to put on.` } });
    } catch (caught) {
      setError(errorText(caught));
      setBusy(false);
    }
  };

  const remove = async () => {
    try {
      await api("DELETE", `/stations/${id}`);
      allow();
      navigate(BACK, { state: { said: "Deleted." } });
    } catch (caught) {
      setDeleting(false);
      setError(errorText(caught));
    }
  };

  const ready =
    !!form && !!form.name.trim() && !!form.description.trim() && (!form.dj || !!form.dj_name.trim());

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerStart}>
          <Link to={BACK} aria-label="Back to Radio" className={styles.iconLink}>
            <Icon name="back" />
          </Link>
          <h1 className={styles.title}>{editing ? "Edit station" : "New AI station"}</h1>
        </div>
      </header>

      {!form && <FormError message={error} />}
      {form && (
        <form className={styles.columns} onSubmit={submit}>
          <div className={styles.stack}>
            <Section title="Station">
              <TextField
                label="Name"
                value={form.name}
                maxLength={100}
                placeholder="Lunchtime Grooves"
                onChange={(event) => change({ name: event.target.value })}
              />
              <Area
                label="What should it play?"
                value={form.description}
                rows={3}
                placeholder="Upbeat soul, funk and Motown for the lunch hour. Nothing too slow."
                onChange={(description) => change({ description })}
              />
              <SwitchRow
                label="Global awareness"
                hint="Uses the time of day, the weather where the office is, and music news, like an artist's passing or a song contest winner."
                checked={form.global_awareness}
                onChange={(global_awareness) => change({ global_awareness })}
              />
              {editing ? (
                <Cover
                  stationId={Number(id)}
                  url={art}
                  name={form.name.trim()}
                  description={form.description.trim()}
                  onPainted={setArt}
                  onError={setError}
                />
              ) : (
                <p className={styles.muted}>
                  Once it's created, OpenAI paints its cover from the name and description.
                </p>
              )}
            </Section>
            <p className={styles.muted}>
              The AI picks the songs from your description and what's played lately, and finds
              them on Spotify. Requests always play first, and thumbs down skip a song, but votes
              never change the station's taste.
            </p>
            <Section title="Jingles">
              <SwitchRow
                label="Play jingles"
                hint="GuildFM's system idents and this station's own station idents, in the pause between songs. The AI chooses where."
                checked={form.jingles}
                onChange={(jingles) => change({ jingles })}
              />
              {form.jingles &&
                (editing ? (
                  <div className={e.field}>
                    <span className={e.label}>Station idents</span>
                    <JingleList
                      stationId={Number(id)}
                      empty="None yet. Without its own, the station plays GuildFM's system idents."
                    />
                  </div>
                ) : (
                  <p className={styles.muted}>
                    Create the station first, then come back to add its own station idents.
                  </p>
                ))}
            </Section>
          </div>

          <div className={styles.stack}>
            <DJ
              form={form}
              stationId={editing ? Number(id) : null}
              onChange={change}
              onError={setError}
            />
            <Button
              variant="secondary"
              block
              disabled={!ready}
              onClick={() => setPreviewing(form)}
            >
              <Icon name="radio" size={18} />
              Preview an hour
            </Button>
            <FormError message={error} />
            <div className={e.actions}>
              <ButtonLink variant="secondary" block to={BACK}>
                Cancel
              </ButtonLink>
              <Button type="submit" block disabled={busy || !ready}>
                {editing ? "Save" : "Create station"}
              </Button>
            </div>
            {editing && (
              <Button variant="ghost" className={e.delete} onClick={() => setDeleting(true)}>
                Delete station
              </Button>
            )}
          </div>
        </form>
      )}

      {previewing && (
        <HourPreview
          open
          onClose={() => setPreviewing(null)}
          station={previewing}
          stationId={editing ? Number(id) : null}
        />
      )}

      {leaving}

      <Dialog open={deleting} onClose={() => setDeleting(false)} title="Delete this station?">
        <p className={styles.muted}>
          If it's on, nothing fills the gaps between requests until the queue runs out.
        </p>
        <div className={e.actions}>
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

function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  const id = useId();
  return (
    <section className={styles.section} aria-labelledby={id}>
      <div className={e.sectionTop}>
        <h2 id={id} className={styles.sectionTitle}>
          {title}
        </h2>
        {aside}
      </div>
      <div className={styles.card}>{children}</div>
    </section>
  );
}

type CoverProps = {
  stationId: number;
  url: string | null;
  /** As they are in the form, saved or not: what the new cover is painted from. */
  name: string;
  description: string;
  onPainted: (url: string | null) => void;
  onError: (message: string | null) => void;
};

/** The station's cover, standing in for album art, and a button for another. */
function Cover({ stationId, url, name, description, onPainted, onError }: CoverProps) {
  const [busy, setBusy] = useState(false);

  const repaint = async () => {
    setBusy(true);
    onError(null);
    try {
      const station = await api<Station>("POST", `/stations/${stationId}/cover`, {
        name,
        description,
      });
      onPainted(station.art_url);
    } catch (caught) {
      onError(errorText(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={e.cover}>
      <StationCover url={url} className={e.coverArt} iconSize={34} />
      <div className={e.coverText}>
        <span className={e.rowHint}>
          Painted by OpenAI from the name and description above, saved or not. Saving a new
          name or description paints a new one, unless this cover was painted from them.
        </span>
        <Button variant="secondary" disabled={busy || !name || !description} onClick={repaint}>
          {busy ? "Painting, about half a minute..." : url ? "Paint another" : "Paint one"}
        </Button>
      </div>
    </div>
  );
}

type AreaProps = {
  label: string;
  value: string;
  rows: number;
  placeholder?: string;
  onChange: (value: string) => void;
};

function Area({ label, value, rows, placeholder, onChange }: AreaProps) {
  const id = useId();
  return (
    <div className={e.field}>
      <label htmlFor={id} className={e.label}>
        {label}
      </label>
      <textarea
        id={id}
        rows={rows}
        maxLength={600}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className={e.textarea}
      />
    </div>
  );
}

type SwitchRowProps = {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
};

function SwitchRow({ label, hint, checked, onChange }: SwitchRowProps) {
  const id = useId();
  return (
    <div className={e.row}>
      <span className={e.rowText}>
        <span id={id} className={e.rowLabel}>
          {label}
        </span>
        {hint && <span className={e.rowHint}>{hint}</span>}
      </span>
      <Toggle checked={checked} onChange={onChange} labelledBy={id} />
    </div>
  );
}

type DJProps = {
  form: StationFields;
  /** The station being edited, or null for a new one. */
  stationId: number | null;
  onChange: (changes: Partial<StationFields>) => void;
  onError: (message: string | null) => void;
};

function DJ({ form, stationId, onChange, onError }: DJProps) {
  const switchId = useId();
  const everyId = useId();
  const [phrase, setPhrase] = useState("intro");
  const [own, setOwn] = useState("");
  const [djs, setDjs] = useState<DJProfile[]>([]);
  const voices = useVoices();

  useEffect(() => {
    api<DJProfile[]>("GET", "/djs")
      .then(setDjs)
      .catch((caught) => onError(errorText(caught)));
  }, [onError]);

  const host = djs.find((dj) => dj.id === form.dj_id);
  const elsewhere = (host?.stations ?? [])
    .filter((station) => station.id !== stationId)
    .map((station) => station.name);
  const choose = (dj: DJProfile | null) =>
    onChange(
      dj
        ? { dj_id: dj.id, dj_name: dj.name, personality: dj.personality, voice: dj.voice }
        : { dj_id: null, dj_name: "", personality: "", voice: "marin" },
    );
  const tags = isEleven(form.voice);
  const chosen = PHRASES.find((p) => p.id === phrase) ?? PHRASES[0];
  const words = phrase === "custom" ? own : tags ? chosen.tagged : chosen.text;
  const voice = voiceName(form.voice, voices);

  return (
    <Section
      title="DJ"
      aside={
        <span className={e.djSwitch}>
          <span id={switchId} className={e.rowHint}>
            Use a DJ
          </span>
          <Toggle checked={form.dj} onChange={(dj) => onChange({ dj })} labelledBy={switchId} />
        </span>
      }
    >
      {!form.dj && <p className={styles.muted}>Music only. Announcements still play on schedule.</p>}
      {form.dj && (
        <>
          {djs.length > 0 && (
            <fieldset className={e.group}>
              <legend className={e.label}>Which DJ</legend>
              <div className={e.chips}>
                {djs.map((dj) => (
                  <button
                    key={dj.id}
                    type="button"
                    aria-pressed={form.dj_id === dj.id}
                    className={e.chip}
                    onClick={() => choose(dj)}
                  >
                    {dj.name}
                  </button>
                ))}
                <button
                  type="button"
                  aria-pressed={form.dj_id === null}
                  className={e.chip}
                  onClick={() => choose(null)}
                >
                  New DJ
                </button>
              </div>
              <span className={e.rowHint}>
                {form.dj_id === null
                  ? "Saving makes a new DJ, who can host other stations too."
                  : elsewhere.length > 0
                    ? `${host?.name} also hosts ${listed(elsewhere)}. Changes to the name, ` +
                      "personality or voice apply there too."
                    : "A DJ can host other stations too. How often they talk is up to each station."}
              </span>
            </fieldset>
          )}
          <TextField
            label="DJ name"
            value={form.dj_name}
            maxLength={40}
            placeholder="Della"
            onChange={(event) => onChange({ dj_name: event.target.value })}
          />
          <Area
            label="Personality"
            value={form.personality}
            rows={3}
            placeholder="Warm, upbeat northern host. Loves a bit of music trivia, never talks for long."
            onChange={(personality) => onChange({ personality })}
          />

          <fieldset className={e.group}>
            <legend className={e.label}>Voice</legend>
            <span className={e.voiceKind}>OpenAI</span>
            <div className={e.chips}>
              {(voices?.openai ?? VOICES).map((name) => (
                <button
                  key={name}
                  type="button"
                  aria-pressed={form.voice === name}
                  className={e.chip}
                  onClick={() => onChange({ voice: name })}
                >
                  {voiceName(name, voices)}
                </button>
              ))}
            </div>
            <span className={e.rowHint}>Marin and Cedar sound the most natural.</span>
            {voices && voices.elevenlabs.length > 0 && (
              <>
                <span className={e.voiceKind}>ElevenLabs</span>
                <div className={e.chips}>
                  {voices.elevenlabs.map((found) => (
                    <button
                      key={found.id}
                      type="button"
                      aria-pressed={form.voice === found.id}
                      className={e.chip}
                      onClick={() => onChange({ voice: found.id })}
                    >
                      {found.name}
                    </button>
                  ))}
                </div>
                <span className={e.rowHint}>
                  Your own voices from ElevenLabs. The DJ can act them out with tags like
                  [laughs] or [sighs].
                </span>
              </>
            )}
          </fieldset>

          <div className={e.preview}>
            <span className={e.label}>
              Preview {voice}
              {form.dj_name.trim() ? ` as ${form.dj_name.trim()}` : ""}
            </span>
            <div className={e.chips}>
              {PHRASES.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  aria-pressed={phrase === p.id}
                  className={e.chip}
                  onClick={() => setPhrase(p.id)}
                >
                  {p.label}
                </button>
              ))}
            </div>
            {phrase === "custom" ? (
              <Area
                label="Your phrase"
                value={own}
                rows={2}
                placeholder="Type anything for the DJ to say"
                onChange={setOwn}
              />
            ) : (
              <p className={e.phrase}>“{tags ? chosen.tagged : chosen.text}”</p>
            )}
            <div className={e.previewFoot}>
              <span className={e.rowHint}>
                Plays here, not on the office speakers. The delivery follows the personality.
              </span>
              <PreviewButton
                text={words}
                onError={onError}
                endpoint="/stations/preview"
                extra={{ voice: form.voice, dj_name: form.dj_name, personality: form.personality }}
              />
            </div>
          </div>

          <fieldset className={e.group}>
            <legend className={e.label}>How often the DJ talks</legend>
            <div className={e.every}>
              <label htmlFor={everyId} className={e.rowHint}>
                Every
              </label>
              <input
                id={everyId}
                type="number"
                min={1}
                max={120}
                value={form.talk_every}
                onChange={(event) =>
                  onChange({ talk_every: Math.max(1, Math.min(120, Number(event.target.value) || 1)) })
                }
                className={e.number}
              />
              <SegmentedControl
                label="Unit"
                options={[
                  { value: "tracks", label: "tracks" },
                  { value: "minutes", label: "minutes" },
                ]}
                value={form.talk_unit}
                onChange={(talk_unit) => onChange({ talk_unit })}
              />
            </div>
          </fieldset>

          <fieldset className={e.group}>
            <legend className={e.label}>What the DJ says</legend>
            <ChoiceCards
              label="What the DJ says"
              choices={STYLES}
              value={form.style}
              onChange={(style) => onChange({ style })}
            />
          </fieldset>

          <SwitchRow
            label="Announce requests"
            hint="Says who asked for the song, unless they've opted out."
            checked={form.announce_requests}
            onChange={(announce_requests) => onChange({ announce_requests })}
          />
          <p className={styles.muted}>
            The DJ chooses whether to talk over the start of a song or between songs, and mixes
            both. Announcements always go first.
          </p>
        </>
      )}
    </Section>
  );
}
