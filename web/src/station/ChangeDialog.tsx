import { useState } from "react";
import { api, type DJProfile, errorText, type Station, type Voices } from "../api";
import { Button } from "../components/Button";
import { Dialog } from "../components/Dialog";
import { FormError } from "../components/TextField";
import { listed } from "../pages/announcementText";
import { type Draft, draftOf, hostsOf, type Kind, kindOf, missing, sent, type Step, stepTitle } from "./kinds";
import { StepView } from "./StepView";
import p from "./StationPage.module.css";

/** The steps a change opens: just its own, or, for a new type, the ones the type needs. */
function chainFor(kind: Kind, saved: Kind): Step[] {
  if (kind === saved || kind === "music") return ["type"];
  return kind === "dj" ? ["type", "djs", "talking"] : ["type", "djs", "show"];
}

type Props = {
  station: Station;
  /** The part being changed. */
  start: Step;
  voices: Voices | null;
  known: DJProfile[];
  onClose: () => void;
  /** Saved, with a word to say so. */
  onSaved: (station: Station, said: string) => void;
};

/** One part of a station, changed on a copy of it and saved on its own: a dialog on a wide
 * screen, the whole screen on a phone. A new type walks through the steps it needs. */
export function ChangeDialog({ station, start, voices, known, onClose, onSaved }: Props) {
  const saved = kindOf(station);
  const [draft, setDraft] = useState<Draft>(() => draftOf(station));
  const [chain, setChain] = useState<Step[]>([start]);
  const [at, setAt] = useState(0);
  const [djEditing, setDJEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const step = chain[at];
  const last = at === chain.length - 1;

  const change = (changes: Partial<Draft>) => setDraft((current) => ({ ...current, ...changes }));

  const pick = (kind: Kind) => {
    // Back to the type it has: its own DJs again, as saved.
    const own = kind === saved;
    setDraft((current) => ({
      ...current,
      kind,
      djs: own ? draftOf(station).djs : current.djs,
      spare: own ? [] : current.spare,
    }));
    setChain(chainFor(kind, saved));
  };

  const why = step === "djs" && djEditing ? "Finish with the DJ's details, or cancel them." : missing(step, draft, voices);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      // A station with more DJs than it uses keeps them unless its DJ was changed.
      const result = await api<Station>("PUT", `/stations/${station.id}`, sent(draft, !chain.includes("djs")));
      onSaved(result, said(result));
    } catch (caught) {
      setError(errorText(caught));
      setBusy(false);
    }
  };

  const said = (result: Station): string => {
    if (draft.kind === "music" && saved !== "music") {
      const off = hostsOf(draftOf(station)).map((dj) => dj.name);
      const stay = off.length === 1 ? "stays" : "stay";
      return `Saved. ${result.name} is just music now. ${listed(off)} ${stay} for other stations.`;
    }
    if (result.name !== station.name || result.description !== station.description) {
      return "Saved. A new cover is being painted.";
    }
    return "Saved.";
  };

  const next = () => {
    if (why) return;
    if (last) void save();
    else setAt(at + 1);
  };

  return (
    <Dialog
      open
      full
      onClose={onClose}
      title={stepTitle(step, draft.kind)}
      footer={
        <div className={p.dialogFoot}>
          <p className={p.why}>{why}</p>
          <div className={p.dialogButtons}>
            <Button variant="secondary" onClick={() => (at > 0 ? setAt(at - 1) : onClose())}>
              {at > 0 ? "Back" : "Cancel"}
            </Button>
            <Button disabled={!!why || busy} onClick={next}>
              {last ? (busy ? "Saving..." : "Save") : `Next: ${stepTitle(chain[at + 1], draft.kind)}`}
            </Button>
          </div>
        </div>
      }
    >
      {chain.length > 1 && (
        <p className={p.chain}>
          Step {at + 1} of {chain.length}: changing the type
        </p>
      )}
      <StepView
        key={step}
        step={step}
        draft={draft}
        place="dialog"
        change={change}
        voices={voices}
        known={known}
        stationId={station.id}
        saved={saved}
        onPick={pick}
        onError={setError}
        onEditing={setDJEditing}
      />
      <FormError message={error} />
    </Dialog>
  );
}
