import { Fragment, type ReactNode, useId, useRef, useState } from "react";
import { api, errorText, type Feature, type Voices } from "../api";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import { usePreview } from "../components/PreviewButton";
import { FormError, TextField } from "../components/TextField";
import { listed } from "../pages/announcementText";
import {
  creditsAnHour,
  type Draft,
  FEATURE_IDEAS,
  HOT,
  hostsOf,
  hourText,
  LEAST_TALK,
  lead,
  MOST_FEATURES,
  mixText,
} from "./kinds";
import { Area, type Place, StepBox, SwitchRow } from "./parts";
import s from "./Steps.module.css";

/** The named fields a script prompt can use, as fields.py has them. */
export const FIELDS = [
  { name: "news", label: "Odd news" },
  { name: "oddities", label: "Odd facts and history" },
  { name: "weather", label: "Weather" },
  { name: "sports", label: "Football" },
  { name: "celebrities", label: "Birthdays and celebs" },
  { name: "lineup", label: "What's on next" },
  { name: "djs", label: "The other DJs" },
];
const FIELD = new RegExp(`\\[(${FIELDS.map((f) => f.name).join("|")})\\]`, "gi");
const MOST_PROMPT = 4000;

type Props = {
  draft: Draft;
  place: Place;
  change: (changes: Partial<Draft>) => void;
  voices: Voices | null;
  onError: (message: string | null) => void;
};

/** A talk show's mix of talk and music, what it's about, and how its hosts get on. */
export function ShowStep({ draft, place, change, voices, onError }: Props) {
  return (
    <StepBox place={place} lead={lead("show", draft, place === "dialog")}>
      <Mix ratio={draft.talk_ratio} credits={voices?.credits_limit ?? null} onChange={(talk_ratio) => change({ talk_ratio })} />
      <div className={s.panel}>
        <Prompt value={draft.script_prompt} onChange={(script_prompt) => change({ script_prompt })} />
      </div>
      <div className={s.panel}>
        <Features features={draft.features} onChange={(features) => change({ features })} />
      </div>
      <div className={s.panel}>
        <GetOn draft={draft} change={change} onError={onError} />
      </div>
      <SwitchRow
        className={s.boxed}
        label="Say who asked for a song"
        hint="Unless they've turned that off on their Profile."
        checked={draft.announce_requests}
        onChange={(announce_requests) => change({ announce_requests })}
      />
    </StepBox>
  );
}

/** Twelve five-minute blocks of an hour, as much of it talk as `ratio` says. */
export function HourStrip({ ratio }: { ratio: number }) {
  const talking = Math.round((ratio / 100) * 12);
  return (
    <div className={s.strip} aria-hidden="true">
      {Array.from({ length: 12 }, (_, block) => (
        <span key={block} className={block < talking ? s.talking : undefined} />
      ))}
    </div>
  );
}

function Mix({ ratio, credits, onChange }: { ratio: number; credits: number | null; onChange: (ratio: number) => void }) {
  const id = useId();
  const hintId = useId();
  const hot = ratio > HOT;
  const perHour = creditsAnHour(ratio);
  const hours = credits ? Math.max(1, Math.round(credits / perHour)) : null;
  return (
    <div className={`${s.panel} ${hot ? s.hot : ""}`}>
      <div className={s.labelRow}>
        <label htmlFor={id} className={s.label}>
          How much talk?
        </label>
        <span className={s.readout}>{mixText(ratio)}</span>
      </div>
      <input
        id={id}
        type="range"
        min={LEAST_TALK}
        max={100}
        step={5}
        value={ratio}
        aria-describedby={hintId}
        aria-valuetext={mixText(ratio)}
        onChange={(event) => onChange(Number(event.target.value))}
        className={s.range}
      />
      <HourStrip ratio={ratio} />
      <p className={s.hourLine}>{hourText(ratio)}</p>
      {hot && (
        <p className={s.hotLine}>
          {ratio >= 100
            ? "All talk: the costliest, with no music but requests."
            : `Over ${HOT}% is mostly talk: costly, with very little music.`}
        </p>
      )}
      <p id={hintId} className={s.hint}>
        About <strong className={s.credits}>{perHour.toLocaleString("en-GB")}</strong> ElevenLabs
        credits an hour
        {hours ? `. This month's allowance covers about ${hours} ${hours === 1 ? "hour" : "hours"} of it.` : "."}
      </p>
    </div>
  );
}

/** The prompt with its named fields picked out, as the textarea over it shows its text. */
function marked(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(FIELD)) {
    const at = match.index ?? 0;
    parts.push(<Fragment key={`t${at}`}>{text.slice(last, at)}</Fragment>);
    parts.push(
      <mark key={`f${at}`} className={s.fieldMark}>
        {match[0]}
      </mark>,
    );
    last = at + match[0].length;
  }
  // A last empty line needs something in it to take up its height.
  parts.push(<Fragment key="end">{text.slice(last) + (text.endsWith("\n") || !text ? " " : "")}</Fragment>);
  return parts;
}

/** `text` without the field `name`, and without the spaces it leaves. */
function withoutField(text: string, name: string): string {
  return text
    .replace(new RegExp(`\\s*\\[${name}\\]`, "gi"), "")
    .replace(/ {2,}/g, " ")
    .replace(/ ([.,;:!?)])/g, "$1")
    .trim();
}

function Prompt({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const id = useId();
  const hintId = useId();
  const area = useRef<HTMLTextAreaElement>(null);
  // Where the cursor was when the prompt was last left, for bringing a field in; the end until then.
  const cursor = useRef<[number, number] | null>(null);
  const used = new Set([...value.matchAll(FIELD)].map((match) => match[1].toLowerCase()));

  const remember = () => {
    const textarea = area.current;
    if (textarea) cursor.current = [textarea.selectionStart, textarea.selectionEnd];
  };

  const bringIn = (name: string) => {
    const [start, end] = cursor.current ?? [value.length, value.length];
    const before = value.slice(0, start);
    const after = value.slice(end);
    const token =
      (before && !/\s$/.test(before) ? " " : "") +
      `[${name}]` +
      (after && !/^[\s.,;:!?)]/.test(after) ? " " : "");
    const next = before + token + after;
    if (next.length > MOST_PROMPT) return;
    onChange(next);
    const caret = before.length + token.length;
    cursor.current = [caret, caret];
  };

  const flip = (name: string) => {
    if (used.has(name)) {
      onChange(withoutField(value, name));
      cursor.current = null;
    } else {
      bringIn(name);
    }
  };

  return (
    <>
      <div className={s.field}>
        <label htmlFor={id} className={s.label}>
          What's it about?
        </label>
        <div className={s.prompt}>
          <div className={s.promptMirror} aria-hidden="true">
            {marked(value)}
          </div>
          <textarea
            ref={area}
            id={id}
            rows={5}
            maxLength={MOST_PROMPT}
            value={value}
            placeholder="A lunchtime show of light chat between them, with plenty of back and forth."
            aria-describedby={hintId}
            onChange={(event) => onChange(event.target.value)}
            onSelect={remember}
            onBlur={remember}
            className={s.promptArea}
          />
        </div>
      </div>
      <div className={s.field}>
        <span className={s.rowHint}>Bring in what's going on today</span>
        <div className={s.examples}>
          {FIELDS.map((field) => (
            <button
              key={field.name}
              type="button"
              aria-pressed={used.has(field.name)}
              className={s.chip}
              title={`[${field.name}]`}
              onClick={() => flip(field.name)}
            >
              <Icon name={used.has(field.name) ? "check" : "plus"} size={14} strokeWidth={2.6} />
              {field.label}
            </button>
          ))}
        </div>
      </div>
      <p id={hintId} className={s.hint}>
        A guide, not a script. GuildFM writes the banter, the running jokes and the surprises, and
        strays from this now and then for variety. It looks up only what the prompt brings in,
        before each show.
      </p>
    </>
  );
}

/** The show's own features: bits that come round, one a link, in place of the banter. */
function Features({ features, onChange }: { features: Feature[]; onChange: (features: Feature[]) => void }) {
  const full = features.length >= MOST_FEATURES;
  const has = (name: string) => features.some((f) => f.name.trim().toLowerCase() === name.toLowerCase());
  const set = (index: number, changes: Partial<Feature>) =>
    onChange(features.map((feature, at) => (at === index ? { ...feature, ...changes } : feature)));

  return (
    <>
      <div className={s.labelRow}>
        <span className={s.label}>Features</span>
        <span className={s.count}>
          {features.length} of {MOST_FEATURES}
        </span>
      </div>
      <p className={s.hint}>
        Bits that come round, one each time they talk, in place of the usual banter. Other DJs
        still drop in now and then. With none, it's banter, bets and the odd argument.
      </p>
      {features.length > 0 && (
        <ol className={s.features}>
          {features.map((feature, index) => (
            // Features have no ids, and a name can be changed, so they're known by their place.
            <li key={index} className={s.feature}>
              <div className={s.featureTop}>
                <TextField
                  label="Name"
                  value={feature.name}
                  maxLength={40}
                  placeholder="Joke of the Day"
                  onChange={(event) => set(index, { name: event.target.value })}
                />
                <button
                  type="button"
                  className={s.close}
                  aria-label={`Take off ${feature.name.trim() || "this feature"}`}
                  onClick={() => onChange(features.filter((_, at) => at !== index))}
                >
                  <Icon name="close" size={20} />
                </button>
              </div>
              <Area
                label="How it works"
                value={feature.does}
                rows={2}
                maxLength={300}
                placeholder="One tells a proper joke, and the other rates it out of ten."
                onChange={(does) => set(index, { does })}
              />
            </li>
          ))}
        </ol>
      )}
      <div className={s.field}>
        <span className={s.rowHint}>Ideas to start from</span>
        <div className={s.examples}>
          {FEATURE_IDEAS.map((idea) => (
            <button
              key={idea.name}
              type="button"
              aria-pressed={has(idea.name)}
              disabled={!has(idea.name) && full}
              className={s.chip}
              title={idea.does}
              onClick={() =>
                onChange(
                  has(idea.name)
                    ? features.filter((f) => f.name.trim().toLowerCase() !== idea.name.toLowerCase())
                    : [...features, idea],
                )
              }
            >
              <Icon name={has(idea.name) ? "check" : "plus"} size={14} strokeWidth={2.6} />
              {idea.name}
            </button>
          ))}
        </div>
      </div>
      <div className={s.buttons}>
        <Button variant="secondary" disabled={full} onClick={() => onChange([...features, { name: "", does: "" }])}>
          <Icon name="plus" size={16} />
          Add your own
        </Button>
      </div>
    </>
  );
}

/** How the hosts get on: written, suggested by the AI, and heard. */
function GetOn({ draft, change, onError }: { draft: Draft; change: (changes: Partial<Draft>) => void; onError: (message: string | null) => void }) {
  const hosts = hostsOf(draft);
  const names = hosts.map((dj) => dj.name);
  const [suggesting, setSuggesting] = useState(false);
  // What was there before the last suggestion, to put back.
  const [before, setBefore] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const { status, play, stop } = usePreview();
  const enough = hosts.length >= 2;

  const suggest = async () => {
    setSuggesting(true);
    setProblem(null);
    try {
      const { dynamic } = await api<{ dynamic: string }>("POST", "/stations/dynamic", {
        name: draft.name,
        djs: hosts,
        script_prompt: draft.script_prompt,
      });
      setBefore(draft.dynamic.trim() ? draft.dynamic : null);
      change({ dynamic });
    } catch (caught) {
      setProblem(errorText(caught));
    } finally {
      setSuggesting(false);
    }
  };

  const together = () => {
    if (status !== "idle") {
      stop();
      return;
    }
    onError(null);
    setProblem(null);
    play("/stations/together", {
      name: draft.name,
      djs: hosts,
      dynamic: draft.dynamic,
      script_prompt: draft.script_prompt,
    }).catch((caught) => setProblem(errorText(caught)));
  };

  const [a, b] = [names[0] ?? "Guildbert", names[1] ?? "Debbie"];
  return (
    <>
      <Area
        label={names.length >= 2 ? `How do ${listed(names)} get on?` : "How do they get on?"}
        value={draft.dynamic}
        rows={4}
        maxLength={1000}
        placeholder={`${a} finds ${b} far too energetic. ${b} can't let ${a} finish a story.`}
        hint="Who winds whom up, and who interrupts whom. It comes up in every show, so keep running jokes in a DJ's pet peeves and obsessions."
        onChange={(dynamic) => {
          setBefore(null);
          change({ dynamic });
        }}
      />
      <div className={s.buttons}>
        <Button variant="secondary" disabled={!enough || suggesting} onClick={suggest}>
          <Icon name="sparkle" size={16} />
          {suggesting ? "Writing..." : draft.dynamic.trim() ? "Suggest another" : "Suggest one"}
        </Button>
        <Button variant="secondary" disabled={!enough} onClick={together}>
          <Icon name={status === "playing" ? "stop" : "headphones"} size={16} />
          {status === "loading"
            ? "Writing and voicing, about half a minute..."
            : status === "playing"
              ? "Stop"
              : "Hear them together"}
        </Button>
        {before !== null && (
          <Button
            variant="ghost"
            onClick={() => {
              change({ dynamic: before });
              setBefore(null);
            }}
          >
            Put back what was there
          </Button>
        )}
      </div>
      <p className={s.hint}>
        {enough
          ? "Hear them together plays half a minute of them, on this device. About 200 credits."
          : "With two or more hosts, the AI can suggest how they get on, and you can hear them together."}
      </p>
      <FormError message={problem} />
    </>
  );
}
