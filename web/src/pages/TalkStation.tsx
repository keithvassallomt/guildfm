import { Fragment, type ReactNode, useId, useRef } from "react";
import type { StationFields, Voices } from "../api";
import { Icon } from "../components/Icon";
import { isEleven } from "../components/useVoices";
import { listed } from "./announcementText";
import styles from "./Page.module.css";
import e from "./StationEditor.module.css";
import { talkable } from "./StationDJs";
import { HeadingSwitch, Section } from "./StationParts";

/** ElevenLabs credits a minute of talk costs, as measured on eleven_v4 (talk.md). */
const CREDITS_A_MINUTE = 450;
/** Above this much talk, the slider turns red: costly, with very little music. */
const HOT = 70;
const LEAST = 20;

/** The named fields a script prompt can use, as fields.py has them. */
const FIELDS = [
  { name: "news", about: "Light, odd and funny stories" },
  { name: "weather", about: "The weather where the office is" },
  { name: "sports", about: "British football: news, scores and results" },
  { name: "celebrities", about: "Birthdays, anniversaries and news" },
  { name: "lineup", about: "What's on for the rest of the day" },
  { name: "djs", about: "GuildFM's other DJs" },
];
const FIELD = new RegExp(`\\[(${FIELDS.map((f) => f.name).join("|")})\\]`, "gi");

const PROMPT_PLACEHOLDER =
  "A lunchtime show of light chat between them, with plenty of back and forth. Draw on the " +
  "day's odd and funny news [news], and the weather [weather].";

type Props = {
  form: StationFields;
  voices: Voices | null;
  onChange: (changes: Partial<StationFields>) => void;
};

/** Whether the station is mostly its DJs talking, how much, and what about. */
export function TalkStation({ form, voices, onChange }: Props) {
  const djs = form.dj ? form.djs : [];
  const can = talkable(djs);
  const on = form.talk_station && can;
  return (
    <Section
      title="Talk station"
      aside={
        <HeadingSwitch
          label="Mostly talk"
          checked={on}
          disabled={!can}
          onChange={(talk_station) => onChange({ talk_station })}
        />
      }
    >
      {!can && (
        <div className={e.notYet}>
          <span className={e.notYetIcon}>
            <Icon name="users" size={18} />
          </span>
          <p className={e.phrase}>{whyNot(form, voices)}</p>
        </div>
      )}
      {can && !on && (
        <p className={styles.muted}>
          A music station, with its first DJ talking between songs as often as the DJ settings
          say. Turn this on for a show that's mostly the DJs chatting.
        </p>
      )}
      {on && (
        <>
          <p className={styles.muted}>
            The DJs chat, bicker and banter, with running bits that carry through the show. The
            AI writes their script from the prompt below.
          </p>
          <Ratio
            ratio={form.talk_ratio}
            credits={voices?.credits_limit ?? null}
            onChange={(talk_ratio) => onChange({ talk_ratio })}
          />
          <ScriptPrompt value={form.script_prompt} onChange={(script_prompt) => onChange({ script_prompt })} />
        </>
      )}
    </Section>
  );
}

/** Why the station can't be a talk station yet, and what would make it one. */
function whyNot(form: StationFields, voices: Voices | null): string {
  const needs = "A talk station needs two or more DJs, each with an ElevenLabs voice.";
  if (voices && !voices.elevenlabs_ready) {
    return `${needs} ElevenLabs isn't set up: it needs ELEVENLABS_API_KEY in GuildFM's .env.`;
  }
  const djs = form.dj ? form.djs : [];
  if (djs.length === 0) return `${needs} Add two in DJs to make it one.`;
  if (djs.length === 1) {
    return `${needs} This one has ${djs[0].name.trim() || "a new DJ"}: add another to make it one.`;
  }
  const openai = djs.filter((dj) => !isEleven(dj.voice)).map((dj) => dj.name.trim() || "the new DJ");
  const has = openai.length === 1 ? "has" : "have";
  return `${needs} ${listed(openai)} ${has} an OpenAI voice: choose an ElevenLabs one to make it one.`;
}

/** Roughly what an hour costs at `ratio` percent talk, to the nearest hundred credits. */
export function creditsAnHour(ratio: number): number {
  return Math.round(((ratio / 100) * 60 * CREDITS_A_MINUTE) / 100) * 100;
}

function Ratio({
  ratio,
  credits,
  onChange,
}: {
  ratio: number;
  credits: number | null;
  onChange: (ratio: number) => void;
}) {
  const id = useId();
  const hintId = useId();
  const hot = ratio > HOT;
  const perHour = creditsAnHour(ratio);
  const hours = credits ? Math.max(1, Math.round(credits / perHour)) : null;
  const at = (percent: number) => `${((percent - LEAST) / (100 - LEAST)) * 100}%`;
  return (
    <div className={`${e.field} ${hot ? e.hot : ""}`}>
      <span className={e.labelRow}>
        <label htmlFor={id} className={e.label}>
          Talk and music
        </label>
        <span className={e.readout}>
          {ratio}% talk · {100 - ratio}% music
        </span>
      </span>
      <div className={e.slider}>
        <span className={e.hotZone} style={{ left: at(HOT) }} aria-hidden="true" />
        <input
          id={id}
          type="range"
          min={LEAST}
          max={100}
          step={5}
          value={ratio}
          aria-describedby={hintId}
          aria-valuetext={`${ratio}% talk, ${100 - ratio}% music`}
          onChange={(event) => onChange(Number(event.target.value))}
          className={e.range}
        />
      </div>
      <div className={e.scale} aria-hidden="true">
        <span style={{ left: at(LEAST) }}>20%</span>
        <span style={{ left: at(HOT) }}>70%</span>
        <span style={{ left: at(100) }}>100%</span>
      </div>
      {hot && (
        <p className={e.hotNote}>
          {ratio >= 100
            ? "All talk: costly, with no music but requests."
            : `Over ${HOT}% is mostly talk: costly, with very little music.`}
        </p>
      )}
      <p id={hintId} className={e.rowHint}>
        About <strong className={e.credits}>{perHour.toLocaleString()}</strong> ElevenLabs credits
        an hour
        {hours ? `, so this month's allowance covers about ${hours} hours of it` : ""}. This sets
        how often the DJs talk, in place of the DJ settings.
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
      <mark key={`f${at}`} className={e.fieldMark}>
        {match[0]}
      </mark>,
    );
    last = at + match[0].length;
  }
  // A last empty line needs something in it to take up its height.
  parts.push(<Fragment key="end">{text.slice(last) + (text.endsWith("\n") || !text ? " " : "")}</Fragment>);
  return parts;
}

function ScriptPrompt({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const id = useId();
  const hintId = useId();
  const area = useRef<HTMLTextAreaElement>(null);
  // Where the cursor was when the prompt was last left, for Add; the end until then.
  const cursor = useRef<[number, number] | null>(null);
  const used = new Set([...value.matchAll(FIELD)].map((match) => match[1].toLowerCase()));

  const remember = () => {
    const textarea = area.current;
    if (textarea) cursor.current = [textarea.selectionStart, textarea.selectionEnd];
  };

  const add = (name: string) => {
    const [start, end] = cursor.current ?? [value.length, value.length];
    const before = value.slice(0, start);
    const after = value.slice(end);
    const token =
      (before && !/\s$/.test(before) ? " " : "") +
      `[${name}]` +
      (after && !/^[\s.,;:!?)]/.test(after) ? " " : "");
    const next = before + token + after;
    if (next.length > 4000) return;
    onChange(next);
    const caret = before.length + token.length;
    cursor.current = [caret, caret];
    requestAnimationFrame(() => {
      area.current?.focus();
      area.current?.setSelectionRange(caret, caret);
    });
  };

  return (
    <>
      <div className={e.field}>
        <label htmlFor={id} className={e.label}>
          Script prompt
        </label>
        <div className={e.prompt}>
          <div className={e.promptMirror} aria-hidden="true">
            {marked(value)}
          </div>
          <textarea
            ref={area}
            id={id}
            rows={7}
            maxLength={4000}
            value={value}
            placeholder={PROMPT_PLACEHOLDER}
            aria-describedby={hintId}
            onChange={(event) => onChange(event.target.value)}
            onSelect={remember}
            onBlur={remember}
            className={e.promptArea}
          />
        </div>
        <span id={hintId} className={e.rowHint}>
          What the show is about. How to sound like two people, the running bits and the
          surprises are GuildFM's job.
        </span>
      </div>

      <div className={e.field}>
        <span className={e.label}>Fields</span>
        <ul className={e.fields}>
          {FIELDS.map((field) => (
            <li key={field.name} className={e.fieldRow}>
              <span className={e.fieldName}>[{field.name}]</span>
              <span className={e.fieldAbout}>{field.about}</span>
              {used.has(field.name) ? (
                <span className={e.inPrompt}>
                  <Icon name="check" size={14} />
                  In the prompt
                </span>
              ) : (
                <button
                  type="button"
                  className={`${e.chip} ${e.chipIcon} ${e.addField}`}
                  aria-label={`Add [${field.name}] to the prompt`}
                  onClick={() => add(field.name)}
                >
                  <Icon name="plus" size={13} />
                  Add
                </button>
              )}
            </li>
          ))}
        </ul>
        <span className={e.rowHint}>
          Add puts the field where the cursor is. GuildFM gathers only the fields the prompt
          uses, before each show.
        </span>
      </div>
    </>
  );
}
