import { useId, useState } from "react";
import { Icon } from "../components/Icon";
import { SegmentedControl } from "../components/SegmentedControl";
import { type Draft, hostsOf, lead, OFTEN, oftenOf, SAYS, sampleLine } from "./kinds";
import { hearLabel, type Place, StepBox, SwitchRow, useHear } from "./parts";
import s from "./Steps.module.css";
import { Button } from "../components/Button";

type Props = {
  draft: Draft;
  place: Place;
  change: (changes: Partial<Draft>) => void;
  onError: (message: string | null) => void;
};

/** How often a station's DJ talks, what they say, and whether they say who asked for a song. */
export function TalkingStep({ draft, place, change, onError }: Props) {
  const everyId = useId();
  // "Let me choose" stays chosen while the numbers match one of the others.
  const [choosing, setChoosing] = useState(() => oftenOf(draft.talk_every, draft.talk_unit) === "custom");
  const often = choosing ? "custom" : oftenOf(draft.talk_every, draft.talk_unit);
  const dj = hostsOf(draft)[0];
  const { hear, state } = useHear(onError);
  const line = sampleLine(dj?.voice ?? "marin", draft.style);
  const shown = line.replace(/\[[a-z ]+\]\s*/g, "");

  return (
    <StepBox place={place} lead={lead("talking", draft, place === "dialog")}>
      <fieldset className={s.group}>
        <legend className={s.label}>How often</legend>
        <div className={`${s.choices} ${s.two}`}>
          {OFTEN.map((option) => (
            <button
              key={option.id}
              type="button"
              aria-pressed={often === option.id}
              className={s.choice}
              onClick={() => {
                setChoosing(false);
                change({ talk_every: option.every, talk_unit: option.unit });
              }}
            >
              <span className={s.choiceLabel}>{option.label}</span>
              <span className={s.choiceHint}>{option.hint}</span>
            </button>
          ))}
          <button
            type="button"
            aria-pressed={often === "custom"}
            className={s.choice}
            onClick={() => setChoosing(true)}
          >
            <span className={s.choiceLabel}>Let me choose</span>
            <span className={s.choiceHint}>Songs or minutes</span>
          </button>
        </div>
        {often === "custom" && (
          <div className={s.every}>
            <label htmlFor={everyId} className={s.rowHint}>
              Every
            </label>
            <input
              id={everyId}
              type="number"
              min={1}
              max={120}
              value={draft.talk_every}
              onChange={(event) =>
                change({ talk_every: Math.max(1, Math.min(120, Number(event.target.value) || 1)) })
              }
              className={s.number}
            />
            <SegmentedControl
              label="Unit"
              options={[
                { value: "tracks", label: "songs" },
                { value: "minutes", label: "minutes" },
              ]}
              value={draft.talk_unit}
              onChange={(talk_unit) => change({ talk_unit })}
            />
          </div>
        )}
      </fieldset>

      <fieldset className={s.group}>
        <legend className={s.label}>What they say</legend>
        <div className={`${s.choices} ${s.twoWide}`}>
          {SAYS.map((say) => (
            <button
              key={say.value}
              type="button"
              aria-pressed={draft.style === say.value}
              className={s.choice}
              onClick={() => change({ style: say.value })}
            >
              <span className={s.choiceLabel}>{say.label}</span>
              <span className={s.choiceHint}>{say.hint}</span>
            </button>
          ))}
        </div>
      </fieldset>

      <div className={s.sample}>
        <span className={s.rowHint}>Something like</span>
        <p className={s.sampleLine}>“{shown}”</p>
        {dj && (
          <div className={s.sampleFoot}>
            <Button variant="secondary" onClick={() => hear("sample", dj, line)}>
              <Icon name={state("sample") === "playing" ? "stop" : "headphones"} size={16} />
              {state("sample") === "idle" ? `Hear ${dj.name} say it` : hearLabel(state("sample"))}
            </Button>
            <span className={s.rowHint}>On this device, not the office speakers.</span>
          </div>
        )}
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
