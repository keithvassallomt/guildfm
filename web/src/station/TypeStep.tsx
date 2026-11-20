import { type KeyboardEvent, useRef } from "react";
import type { DJProfile, Voices } from "../api";
import { Icon, type IconName } from "../components/Icon";
import { isEleven } from "../components/useVoices";
import { type Draft, type Kind, KINDS, lead, talkNotReady, talkReady } from "./kinds";
import { type Place, StepBox } from "./parts";
import s from "./Steps.module.css";

const ICONS: Record<Kind, IconName> = { music: "music", dj: "mic", talk: "chat" };

type Props = {
  draft: Draft;
  place: Place;
  voices: Voices | null;
  known: DJProfile[];
  /** The station's kind as saved, when changing one. */
  saved?: Kind;
  onPick: (kind: Kind) => void;
};

/** What kind of station: just music, music with a DJ, or a talk show. */
export function TypeStep({ draft, place, voices, known, saved, onPick }: Props) {
  const cards = useRef<(HTMLButtonElement | null)[]>([]);
  const talkOff = voices !== null && !talkReady(voices);
  const can = (kind: Kind) => kind !== "talk" || !talkOff;

  const onKeyDown = (event: KeyboardEvent, index: number) => {
    const step = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    let next = index;
    do next = (next + step + KINDS.length) % KINDS.length;
    while (!can(KINDS[next].kind));
    onPick(KINDS[next].kind);
    cards.current[next]?.focus();
  };

  return (
    <StepBox place={place} lead={lead("type", draft, saved !== undefined)}>
      <div
        role="radiogroup"
        aria-label="What kind of station"
        className={`${s.kinds} ${place === "dialog" ? s.listed : ""}`}
      >
        {KINDS.map((k, index) => {
          const picked = draft.kind === k.kind;
          const off = !can(k.kind);
          return (
            <button
              key={k.kind}
              ref={(element) => {
                cards.current[index] = element;
              }}
              type="button"
              role="radio"
              aria-checked={picked}
              aria-disabled={off || undefined}
              tabIndex={picked || (!draft.kind && index === 0) ? 0 : -1}
              className={s.kind}
              onClick={() => !off && onPick(k.kind)}
              onKeyDown={(event) => onKeyDown(event, index)}
            >
              <span className={s.kindIcon}>
                <Icon name={ICONS[k.kind]} size={22} />
              </span>
              <span className={s.kindText}>
                <span className={s.kindTitle}>{k.title}</span>
                <span className={s.kindAbout}>{k.text}</span>
                {place === "wizard" && (
                  <span className={s.kindCost}>{off ? "Needs ElevenLabs" : k.cost}</span>
                )}
              </span>
            </button>
          );
        })}
      </div>

      {talkOff && voices && (
        <p className={`${s.note} ${s.warn}`}>
          <span className={s.noteIcon}>
            <Icon name="info" size={18} />
          </span>
          {talkNotReady(voices)}
        </p>
      )}
      <Note draft={draft} known={known} saved={saved} />
    </StepBox>
  );
}

/** What the kind picked needs, or, when changing a station, what a new kind means. */
function Note({ draft, known, saved }: { draft: Draft; known: DJProfile[]; saved?: Kind }) {
  let text = "";
  let warn = false;
  if (saved !== undefined && draft.kind !== saved) {
    warn = true;
    const had = saved === "talk" ? "Its hosts come" : "Its DJ comes";
    if (draft.kind === "music") {
      text = `${had} off, and it plays music only. The DJs themselves stay, for other stations.`;
    } else if (draft.kind === "dj") {
      text = "Next, choose which DJ is on it, and how often they talk.";
    } else {
      text = "Next, pick the hosts, then shape the show.";
    }
  } else if (draft.kind === "talk" && saved === undefined) {
    const ready = known.filter((dj) => isEleven(dj.voice)).length;
    const needs = "A talk show needs two or more DJs with ElevenLabs voices.";
    const fresh = "any new DJ you make for it gets one too.";
    if (known.length === 0) {
      text = `${needs} You'll make them in the next steps.`;
    } else if (ready === 0) {
      text = `${needs} None of your DJs has one yet: you can give them one in the hosts step, and ${fresh}`;
    } else if (ready === known.length) {
      const all = known.length === 1 ? "Your one DJ has" : `All ${known.length} of your DJs have`;
      text = `${needs} ${all} one, and ${fresh}`;
    } else {
      text = `${needs} ${ready} of your ${known.length} DJs ${ready === 1 ? "has" : "have"} one, and ${fresh}`;
    }
  }
  if (!text) return null;
  return (
    <p className={`${s.note} ${warn ? s.warn : ""}`} role="status">
      <span className={s.noteIcon}>
        <Icon name={warn ? "info" : "check"} size={16} strokeWidth={2.6} />
      </span>
      {text}
    </p>
  );
}
