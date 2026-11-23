import { useId, useState } from "react";
import { type DJProfile, type StationDJ, VOICES, type Voices } from "../api";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import { TextField } from "../components/TextField";
import { isEleven, voiceName } from "../components/useVoices";
import { listed } from "../pages/announcementText";
import { elsewhere, freshHooksText, sampleLine } from "./kinds";
import { Area, hearLabel, SwitchRow, useHear } from "./parts";
import s from "./Steps.module.css";

type Props = {
  /** The DJ as they are, or a blank one for a new DJ. */
  initial: StationDJ;
  isNew: boolean;
  /** Whether saving puts them on the station, rather than changing a DJ who's on it. */
  picks: boolean;
  /** For a talk show: ElevenLabs voices only, and the hooks. */
  talk: boolean;
  voices: Voices | null;
  /** The DJ as saved, for the other stations they host. */
  profile: DJProfile | undefined;
  stationId: number | null;
  /** Other DJs' names, in lower case, which this one can't have. */
  taken: string[];
  /** Why the form opened, such as a DJ needing an ElevenLabs voice for a talk show. */
  reason?: string;
  onDone: (dj: StationDJ) => void;
  onCancel: () => void;
  onError: (message: string | null) => void;
};

/** A DJ's name, personality, voice and, for a talk show, hooks: a new DJ, or one changed. Kept
 * with the station, and saved with it. */
export function DJForm({
  initial,
  isNew,
  picks,
  talk,
  voices,
  profile,
  stationId,
  taken,
  reason,
  onDone,
  onCancel,
  onError,
}: Props) {
  const titleId = useId();
  const [dj, setDJ] = useState<StationDJ>(initial);
  const change = (changes: Partial<StationDJ>) => setDJ((current) => ({ ...current, ...changes }));
  const { hear, state } = useHear(onError);
  const name = dj.name.trim();
  const others = elsewhere(profile, stationId);
  const eleven = voices?.elevenlabs ?? [];

  const why = !name
    ? "Give them a name."
    : taken.includes(name.toLowerCase())
      ? `There's already a DJ called ${name}. Pick them instead.`
      : talk && !isEleven(dj.voice)
        ? "Pick an ElevenLabs voice: a talk show needs one."
        : null;
  const save = isNew || picks ? (name ? `Add ${name}` : "Add DJ") : "Done";

  return (
    <section className={s.form} aria-labelledby={titleId}>
      <div className={s.formTop}>
        <h3 id={titleId} className={s.formTitle}>
          {isNew ? "New DJ" : initial.name}
        </h3>
        <button type="button" aria-label="Cancel" className={s.close} onClick={onCancel}>
          <Icon name="close" size={20} />
        </button>
      </div>
      {reason && (
        <p className={`${s.note} ${s.warn}`}>
          <span className={s.noteIcon}>
            <Icon name="info" size={18} />
          </span>
          {reason}
        </p>
      )}

      <TextField
        label="Name"
        value={dj.name}
        maxLength={40}
        placeholder="Della"
        onChange={(event) => change({ name: event.target.value })}
      />
      <Area
        label="Personality"
        value={dj.personality}
        rows={3}
        placeholder="Warm, upbeat northern host. Loves a bit of music trivia, never talks for long."
        hint="How they talk, their sense of humour, and what they like to talk about."
        onChange={(personality) => change({ personality })}
      />

      <fieldset className={s.group}>
        <legend className={s.label}>Voice</legend>
        <p className={s.hint}>
          {talk
            ? "Talk shows use ElevenLabs voices: they laugh, sigh and talk over each other."
            : "ElevenLabs voices can act out laughs and sighs. OpenAI's cost nothing extra."}
        </p>
        {eleven.length > 0 && (
          <>
            {!talk && <span className={s.voiceKind}>ElevenLabs</span>}
            <div className={`${s.choices} ${s.twoWide}`}>
              {eleven.map((voice) => (
                <button
                  key={voice.id}
                  type="button"
                  aria-pressed={dj.voice === voice.id}
                  className={`${s.choice} ${s.voice}`}
                  onClick={() => change({ voice: voice.id })}
                >
                  <span className={s.choiceLabel}>{voice.name}</span>
                  <span className={s.choiceHint}>{voice.note || "ElevenLabs voice"}</span>
                </button>
              ))}
            </div>
          </>
        )}
        {!talk && (
          <>
            <span className={s.voiceKind}>OpenAI</span>
            <div className={s.voiceChips}>
              {(voices?.openai ?? VOICES).map((voice) => (
                <button
                  key={voice}
                  type="button"
                  aria-pressed={dj.voice === voice}
                  className={s.voiceChip}
                  onClick={() => change({ voice })}
                >
                  {voiceName(voice, voices)}
                </button>
              ))}
            </div>
            <p className={s.hint}>Marin and Cedar sound the most natural.</p>
          </>
        )}
        <div className={s.buttons}>
          <Button
            variant="secondary"
            disabled={talk && !isEleven(dj.voice)}
            onClick={() => hear("form", dj, sampleLine(dj.voice))}
          >
            <Icon name={state("form") === "playing" ? "stop" : "headphones"} size={16} />
            {state("form") === "idle" ? `Hear ${name || "them"}` : hearLabel(state("form"))}
          </Button>
          <span className={s.hint}>
            {voiceName(dj.voice, voices)}, on this device, in the personality above.
          </span>
        </div>
      </fieldset>

      {talk && (
        <div className={s.hooks}>
          <div className={s.rowText}>
            <span className={s.rowLabel}>Something to talk about</span>
            <span className={s.rowHint}>
              Optional. Each show uses one or two of these, so they don't come up every time.
            </span>
          </div>
          <TextField
            label="Pet peeves"
            value={dj.pet_peeves}
            maxLength={300}
            placeholder="Songs that fade out instead of ending."
            onChange={(event) => change({ pet_peeves: event.target.value })}
          />
          <TextField
            label="Soft spots"
            value={dj.soft_spots}
            maxLength={300}
            placeholder="Anything by ABBA. The office dog."
            onChange={(event) => change({ soft_spots: event.target.value })}
          />
          <TextField
            label="Running obsession"
            value={dj.obsession}
            maxLength={200}
            placeholder="Building a shed. Has been for eleven years."
            onChange={(event) => change({ obsession: event.target.value })}
          />
          <SwitchRow
            label="New hooks every month"
            hint={freshHooksText(dj.fresh_hooks, initial.next_hook ?? profile?.next_hook)}
            checked={dj.fresh_hooks}
            onChange={(fresh_hooks) => change({ fresh_hooks })}
          />
        </div>
      )}

      <div className={s.formFoot}>
        <p className={s.hint}>
          {why ??
            (isNew
              ? "Made when the station's saved, as a DJ who can host other stations too."
              : others.length > 0
                ? `Changes to ${initial.name} apply on ${listed(others)} too, once this station's saved.`
                : "Saved with the station.")}
        </p>
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          disabled={!!why}
          onClick={() =>
            onDone({
              ...dj,
              name,
              personality: dj.personality.trim(),
              pet_peeves: dj.pet_peeves.trim(),
              soft_spots: dj.soft_spots.trim(),
              obsession: dj.obsession.trim(),
            })
          }
        >
          {save}
        </Button>
      </div>
    </section>
  );
}
