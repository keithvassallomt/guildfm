import type { Draft } from "./kinds";
import { lead } from "./kinds";
import { Area, type Place, StepBox } from "./parts";
import s from "./Steps.module.css";
import { TextField } from "../components/TextField";

const EXAMPLES = [
  { label: "Lunchtime soul", text: "Upbeat soul, funk and Motown for the lunch hour. Nothing too slow." },
  { label: "Eighties synth-pop", text: "Eighties synth-pop and new wave, with the odd power ballad." },
  { label: "Friday acoustic", text: "Chilled acoustic and indie for Friday afternoons." },
];

const SHOW_EXAMPLES = [
  { label: "Feel-good pop", text: "Feel-good pop from the last thirty years." },
  { label: "Indie classics", text: "Indie and Britpop classics, nothing too heavy." },
  { label: "Eighties and nineties", text: "Big hits from the eighties and nineties, the ones everyone knows the words to." },
];

type Props = {
  draft: Draft;
  place: Place;
  change: (changes: Partial<Draft>) => void;
};

/** The station's name, and the music the AI picks from. */
export function MusicStep({ draft, place, change }: Props) {
  const talk = draft.kind === "talk";
  return (
    <StepBox place={place} lead={lead("music", draft, place === "dialog")}>
      <TextField
        label={talk ? "Show name" : "Station name"}
        value={draft.name}
        maxLength={100}
        placeholder={talk ? "The Squawk Box" : "Lunchtime Grooves"}
        onChange={(event) => change({ name: event.target.value })}
      />
      <Area
        label={talk ? "What plays between the talk?" : "What should it play?"}
        value={draft.description}
        rows={4}
        placeholder={
          talk
            ? "Feel-good pop from the last thirty years."
            : "Upbeat soul, funk and Motown for the lunch hour. Nothing too slow."
        }
        onChange={(description) => change({ description })}
      />
      {place === "wizard" && (
        <div className={s.examples}>
          <span className={s.hint}>Try</span>
          {(talk ? SHOW_EXAMPLES : EXAMPLES).map((example) => (
            <button
              key={example.label}
              type="button"
              className={s.chip}
              onClick={() => change({ description: example.text })}
            >
              {example.label}
            </button>
          ))}
        </div>
      )}
      <p className={s.hint}>
        {place === "wizard"
          ? "The AI picks songs from this and what's played lately, and finds them on Spotify. Requests always play first, and thumbs down skip a song."
          : "Saving a new name or music paints a new cover. Songs already picked still play; new picks follow the new music."}
      </p>
    </StepBox>
  );
}
