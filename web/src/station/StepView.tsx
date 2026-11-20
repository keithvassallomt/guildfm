import type { DJProfile, Voices } from "../api";
import { DJStep } from "./DJStep";
import { ExtrasStep } from "./ExtrasStep";
import type { Draft, Kind, Step } from "./kinds";
import { MusicStep } from "./MusicStep";
import type { Place } from "./parts";
import { ShowStep } from "./ShowStep";
import { TalkingStep } from "./TalkingStep";
import { TypeStep } from "./TypeStep";

type Props = {
  step: Step;
  draft: Draft;
  place: Place;
  change: (changes: Partial<Draft>) => void;
  voices: Voices | null;
  known: DJProfile[];
  /** The station being changed, or null for a new one. */
  stationId: number | null;
  /** Its kind as saved, when changing one. */
  saved?: Kind;
  onPick: (kind: Kind) => void;
  onError: (message: string | null) => void;
  onEditing: (editing: boolean) => void;
};

/** One step of making or changing a station. */
export function StepView({ step, draft, place, change, voices, known, stationId, saved, onPick, onError, onEditing }: Props) {
  switch (step) {
    case "type":
      return <TypeStep draft={draft} place={place} voices={voices} known={known} saved={saved} onPick={onPick} />;
    case "music":
      return <MusicStep draft={draft} place={place} change={change} />;
    case "djs":
      return (
        <DJStep
          draft={draft}
          place={place}
          change={change}
          voices={voices}
          known={known}
          stationId={stationId}
          onError={onError}
          onEditing={onEditing}
        />
      );
    case "talking":
      return <TalkingStep draft={draft} place={place} change={change} onError={onError} />;
    case "show":
      return <ShowStep draft={draft} place={place} change={change} voices={voices} onError={onError} />;
    case "extras":
      return <ExtrasStep draft={draft} place={place} change={change} />;
  }
}
