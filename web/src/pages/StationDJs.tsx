import { useEffect, useId, useState } from "react";
import {
  api,
  type DJProfile,
  errorText,
  type StationDJ,
  type StationFields,
  VOICES,
  type Voices,
} from "../api";
import { Button } from "../components/Button";
import { ChoiceCards } from "../components/ChoiceCards";
import { Icon } from "../components/Icon";
import { PreviewButton, usePreview } from "../components/PreviewButton";
import { SegmentedControl } from "../components/SegmentedControl";
import { FormError, TextField } from "../components/TextField";
import { isEleven, useVoices, voiceName } from "../components/useVoices";
import { listed } from "./announcementText";
import styles from "./Page.module.css";
import e from "./StationEditor.module.css";
import { Area, HeadingSwitch, Section, SwitchRow } from "./StationParts";

/** As many DJs as a station can have (MOST_DJS in api/stations.py). */
export const MOST_DJS = 6;

/** Whether these DJs can make a talk station: two or more, each with an ElevenLabs voice. */
export const talkable = (djs: StationDJ[]) => djs.length >= 2 && djs.every((dj) => isEleven(dj.voice));

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

const HOOKS =
  "For talk stations: what the other DJs can wind them up about, what they go soft on, and " +
  "what they keep coming back to.";

type Props = {
  form: StationFields;
  /** The station being edited, or null for a new one. */
  stationId: number | null;
  /** Whether it's a talk station, as the editor has it. */
  talk: boolean;
  onChange: (changes: Partial<StationFields>) => void;
  onError: (message: string | null) => void;
};

/** The station's DJs: who's on it, each with their details, how they get on, and when they talk. */
export function DJs({ form, stationId, talk, onChange, onError }: Props) {
  const everyId = useId();
  const [known, setKnown] = useState<DJProfile[]>([]);
  // The DJ card that's open, by its place on the station.
  const [open, setOpen] = useState<number | null>(form.djs.length === 1 ? 0 : null);
  const voices = useVoices();

  useEffect(() => {
    api<DJProfile[]>("GET", "/djs")
      .then(setKnown)
      .catch((caught) => onError(errorText(caught)));
  }, [onError]);

  const djs = form.djs;
  const setDJs = (changed: StationDJ[]) => onChange({ djs: changed });
  const update = (index: number, changes: Partial<StationDJ>) =>
    setDJs(djs.map((dj, at) => (at === index ? { ...dj, ...changes } : dj)));
  const remove = (index: number) => {
    setDJs(djs.filter((_, at) => at !== index));
    setOpen((current) => (current === null || current === index ? null : current > index ? current - 1 : current));
  };
  const add = (dj: StationDJ) => {
    setDJs([...djs, dj]);
    setOpen(djs.length);
  };
  const fresh = (): StationDJ => {
    // A talk station's DJs need ElevenLabs voices: one nobody else on it has, if there is one.
    const eleven = voices?.elevenlabs.map((found) => found.id) ?? [];
    const free = eleven.find((id) => !djs.some((dj) => dj.voice === id)) ?? eleven[0];
    return {
      id: null,
      name: "",
      personality: "",
      voice: talk && free ? free : "marin",
      pet_peeves: "",
      soft_spots: "",
      obsession: "",
    };
  };
  const useDJs = (on: boolean) => {
    onChange(on && djs.length === 0 ? { dj: on, djs: [fresh()] } : { dj: on });
    if (on && djs.length === 0) setOpen(0);
  };

  const onIt = new Set(djs.map((dj) => dj.id));
  const others = known.filter((dj) => !onIt.has(dj.id));
  const names = djs.map((dj) => dj.name.trim()).filter(Boolean);

  return (
    <Section title="DJs" aside={<HeadingSwitch label="Use DJs" checked={form.dj} onChange={useDJs} />}>
      {!form.dj && <p className={styles.muted}>Music only. Announcements still play on schedule.</p>}
      {form.dj && (
        <>
          {djs.length > 0 && (
            <div className={e.field}>
              <span className={e.label}>On this station</span>
              {djs.map((dj, index) => (
                <DJCard
                  key={dj.id ?? `new-${index}`}
                  dj={dj}
                  profile={known.find((found) => found.id === dj.id)}
                  stationId={stationId}
                  talk={talk}
                  voices={voices}
                  open={open === index}
                  onToggle={() => setOpen(open === index ? null : index)}
                  onChange={(changes) => update(index, changes)}
                  onRemove={() => remove(index)}
                  onError={onError}
                />
              ))}
            </div>
          )}

          {djs.length < MOST_DJS && (
            <div className={e.field}>
              <span className={e.label}>{djs.length > 0 ? "Add a DJ" : "Choose a DJ"}</span>
              <div className={e.chips}>
                {others.map((dj) => (
                  <button
                    key={dj.id}
                    type="button"
                    className={e.chip}
                    onClick={() =>
                      add({
                        id: dj.id,
                        name: dj.name,
                        personality: dj.personality,
                        voice: dj.voice,
                        pet_peeves: dj.pet_peeves,
                        soft_spots: dj.soft_spots,
                        obsession: dj.obsession,
                      })
                    }
                  >
                    {dj.name}
                  </button>
                ))}
                <button type="button" className={`${e.chip} ${e.chipIcon}`} onClick={() => add(fresh())}>
                  <Icon name="plus" size={13} />
                  New DJ
                </button>
              </div>
              <span className={e.rowHint}>
                {djs.length === 1
                  ? "With a second DJ, you can say how they get on, and make this a talk station."
                  : "A DJ can host any number of stations, and what you change about them changes everywhere they host."}
              </span>
            </div>
          )}

          {djs.length >= 2 && (
            <Together
              names={names}
              djs={djs}
              stationName={form.name}
              dynamic={form.dynamic}
              scriptPrompt={form.script_prompt}
              onChange={(dynamic) => onChange({ dynamic })}
              onError={onError}
            />
          )}

          {talk ? (
            <>
              <fieldset className={e.group} disabled>
                <legend className={e.label}>How often the DJs talk</legend>
                <div className={e.every}>
                  <label htmlFor={everyId} className={e.rowHint}>
                    Every
                  </label>
                  <input id={everyId} type="number" value={form.talk_every} readOnly className={e.number} />
                  <SegmentedControl
                    label="Unit"
                    options={[
                      { value: "tracks", label: "tracks" },
                      { value: "minutes", label: "minutes" },
                    ]}
                    value={form.talk_unit}
                    onChange={() => {}}
                  />
                </div>
              </fieldset>
              <p className={styles.muted}>
                Set by the talk and music slider on a talk station, and what they say by the
                script prompt.
              </p>
            </>
          ) : (
            <>
              <fieldset className={e.group}>
                <legend className={e.label}>
                  {djs.length > 1 ? "How often the DJs talk" : "How often the DJ talks"}
                </legend>
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
                      onChange({
                        talk_every: Math.max(1, Math.min(120, Number(event.target.value) || 1)),
                      })
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
                <legend className={e.label}>
                  {djs.length > 1 ? "What the DJs say" : "What the DJ says"}
                </legend>
                <ChoiceCards
                  label="What the DJ says"
                  choices={STYLES}
                  value={form.style}
                  onChange={(style) => onChange({ style })}
                />
              </fieldset>
              {djs.length > 1 && (
                <p className={styles.muted}>
                  On a music station only the first DJ talks between songs. Make it a talk
                  station for them all.
                </p>
              )}
            </>
          )}

          <SwitchRow
            label="Announce requests"
            hint="Says who asked for the song, unless they've opted out."
            checked={form.announce_requests}
            onChange={(announce_requests) => onChange({ announce_requests })}
          />
          <p className={styles.muted}>
            The DJs talk between songs, so every room hears it in step. Announcements always go
            first.
          </p>
        </>
      )}
    </Section>
  );
}

type CardProps = {
  dj: StationDJ;
  /** The DJ as saved, for the other stations they host. Undefined for a new one. */
  profile: DJProfile | undefined;
  stationId: number | null;
  talk: boolean;
  voices: Voices | null;
  open: boolean;
  onToggle: () => void;
  onChange: (changes: Partial<StationDJ>) => void;
  onRemove: () => void;
  onError: (message: string | null) => void;
};

/** One of the station's DJs: a line that opens into their details. */
function DJCard({ dj, profile, stationId, talk, voices, open, onToggle, onChange, onRemove, onError }: CardProps) {
  const bodyId = useId();
  const [phrase, setPhrase] = useState("intro");
  const [own, setOwn] = useState("");
  const name = dj.name.trim();
  const elsewhere = (profile?.stations ?? [])
    .filter((station) => station.id !== stationId)
    .map((station) => station.name);
  const voice = voiceName(dj.voice, voices);
  const where =
    dj.id === null
      ? "new, saved with the station"
      : elsewhere.length > 0
        ? `also hosts ${listed(elsewhere)}`
        : "only on this station";
  const tags = isEleven(dj.voice);
  const chosen = PHRASES.find((p) => p.id === phrase) ?? PHRASES[0];
  const words = phrase === "custom" ? own : tags ? chosen.tagged : chosen.text;

  return (
    <div className={e.djCard}>
      <button
        type="button"
        className={e.djHead}
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={onToggle}
      >
        <span className={e.initial} aria-hidden="true">
          {(name || "?").charAt(0).toUpperCase()}
        </span>
        <span className={e.rowText}>
          <span className={e.rowLabel}>{name || "New DJ"}</span>
          <span className={e.rowHint}>
            Voice: {voice} · {where}
          </span>
        </span>
        <span className={`${e.chevron} ${open ? e.flipped : ""}`} aria-hidden="true">
          <Icon name="chevronDown" size={20} />
        </span>
      </button>

      {open && (
        <div id={bodyId} className={e.djBody}>
          <TextField
            label="DJ name"
            value={dj.name}
            maxLength={40}
            placeholder="Della"
            onChange={(event) => onChange({ name: event.target.value })}
          />
          <Area
            label="Personality"
            value={dj.personality}
            rows={3}
            placeholder="Warm, upbeat northern host. Loves a bit of music trivia, never talks for long."
            onChange={(personality) => onChange({ personality })}
          />
          <div className={e.hooks}>
            <span className={e.rowHint}>{HOOKS}</span>
            <Area
              label="Pet peeves"
              value={dj.pet_peeves}
              rows={2}
              maxLength={300}
              counted
              placeholder="Songs that fade out instead of ending. People who clap on the one."
              onChange={(pet_peeves) => onChange({ pet_peeves })}
            />
            <Area
              label="Soft spots"
              value={dj.soft_spots}
              rows={2}
              maxLength={300}
              counted
              placeholder="Anything by ABBA. Brass bands. The office dog."
              onChange={(soft_spots) => onChange({ soft_spots })}
            />
            <Area
              label="Running obsession"
              value={dj.obsession}
              rows={2}
              maxLength={200}
              counted
              placeholder="Building a shed. Has been for eleven years."
              onChange={(obsession) => onChange({ obsession })}
            />
          </div>

          <fieldset className={e.group}>
            <legend className={e.label}>Voice</legend>
            {voices && voices.elevenlabs.length > 0 && (
              <>
                <span className={e.voiceKind}>ElevenLabs</span>
                <div className={e.chips}>
                  {voices.elevenlabs.map((found) => (
                    <button
                      key={found.id}
                      type="button"
                      aria-pressed={dj.voice === found.id}
                      className={e.chip}
                      onClick={() => onChange({ voice: found.id })}
                    >
                      {found.name}
                    </button>
                  ))}
                </div>
              </>
            )}
            {talk ? (
              <span className={e.rowHint}>
                Talk stations use ElevenLabs voices: they can laugh, sigh and talk over each
                other. OpenAI's voices are for music stations.
              </span>
            ) : (
              <>
                {voices && voices.elevenlabs.length > 0 && (
                  <span className={e.rowHint}>
                    Your own voices from ElevenLabs. The DJ can act them out with tags like
                    [laughs] or [sighs], and talk over other DJs on a talk station.
                  </span>
                )}
                <span className={e.voiceKind}>OpenAI</span>
                <div className={e.chips}>
                  {(voices?.openai ?? VOICES).map((option) => (
                    <button
                      key={option}
                      type="button"
                      aria-pressed={dj.voice === option}
                      className={e.chip}
                      onClick={() => onChange({ voice: option })}
                    >
                      {voiceName(option, voices)}
                    </button>
                  ))}
                </div>
                <span className={e.rowHint}>Marin and Cedar sound the most natural.</span>
              </>
            )}
          </fieldset>

          <div className={e.preview}>
            <span className={e.label}>
              Preview {voice}
              {name ? ` as ${name}` : ""}
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
              <p className={e.phrase}>“{words}”</p>
            )}
            <div className={e.previewFoot}>
              <span className={e.rowHint}>
                Plays here, not on the office speakers. The delivery follows the personality.
              </span>
              <PreviewButton
                text={words}
                onError={onError}
                endpoint="/stations/preview"
                extra={{ voice: dj.voice, dj_name: dj.name, personality: dj.personality }}
              />
            </div>
          </div>

          <div className={e.djFoot}>
            <span className={e.rowHint}>
              {elsewhere.length > 0
                ? `Changes to ${profile?.name ?? name} apply on ${listed(elsewhere)} too.`
                : dj.id === null
                  ? "Saving makes a new DJ, who can host other stations too."
                  : "A DJ can host other stations too."}
            </span>
            <Button variant="ghost" onClick={onRemove}>
              Take off this station
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

type TogetherProps = {
  names: string[];
  djs: StationDJ[];
  stationName: string;
  dynamic: string;
  scriptPrompt: string;
  onChange: (dynamic: string) => void;
  onError: (message: string | null) => void;
};

/** How the station's DJs get on, and a half-minute of them together to hear it. */
function Together({ names, djs, stationName, dynamic, scriptPrompt, onChange, onError }: TogetherProps) {
  const { status, play, stop } = usePreview();
  const [problem, setProblem] = useState<string | null>(null);
  const openai = djs.filter((dj) => !isEleven(dj.voice)).map((dj) => dj.name.trim() || "the new DJ");
  const named = djs.every((dj) => dj.name.trim());

  const press = () => {
    if (status !== "idle") {
      stop();
      return;
    }
    onError(null);
    setProblem(null);
    play("/stations/together", { name: stationName, djs, dynamic, script_prompt: scriptPrompt }).catch(
      (caught) => setProblem(errorText(caught)),
    );
  };

  return (
    <div className={e.field}>
      <Area
        label="How they get on"
        value={dynamic}
        rows={5}
        maxLength={1000}
        placeholder={
          names.length >= 2
            ? `${names[0]} finds ${names[1]} far too energetic. ${names[1]} can't let ${names[0]} finish a story.`
            : "Who winds whom up, and who interrupts whom."
        }
        hint="What winds each of them up, and who interrupts whom. Belongs to this station, so the same DJs can get on differently elsewhere."
        onChange={onChange}
      />
      <div className={e.together}>
        <Button
          variant="secondary"
          disabled={!named || openai.length > 0}
          onClick={press}
        >
          <Icon name={status === "playing" ? "stop" : "headphones"} size={16} />
          {status === "loading"
            ? "Writing and voicing, about half a minute..."
            : status === "playing"
              ? "Stop"
              : "Hear them together"}
        </Button>
        <span className={e.rowHint}>
          {openai.length > 0
            ? `They need ElevenLabs voices to talk together: ${listed(openai)} ${openai.length === 1 ? "has" : "have"} an OpenAI one.`
            : "A half-minute exchange in their voices, on this device. About 200 credits."}
        </span>
      </div>
      <FormError message={problem} />
    </div>
  );
}
