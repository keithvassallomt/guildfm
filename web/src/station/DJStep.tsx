import { useEffect, useState } from "react";
import type { DJProfile, StationDJ, Voices } from "../api";
import { Icon } from "../components/Icon";
import { isEleven } from "../components/useVoices";
import { listed } from "../pages/announcementText";
import { DJForm } from "./DJForm";
import { asStationDJ, type Draft, elsewhere, hostsOf, lead, MOST_DJS } from "./kinds";
import { Avatar, hearLabel, type Place, StepBox, useHear } from "./parts";
import s from "./Steps.module.css";

/** A DJ on the page, saved or new, by a key that doesn't change while they're edited. */
const keyOf = (dj: StationDJ) => (dj.id !== null ? `id:${dj.id}` : `new:${dj.name.trim().toLowerCase()}`);

type Editing = {
  dj: StationDJ;
  key: string | null; // null for a new DJ
  reason?: string;
};

type Props = {
  draft: Draft;
  place: Place;
  change: (changes: Partial<Draft>) => void;
  voices: Voices | null;
  /** The office's DJs. */
  known: DJProfile[];
  stationId: number | null;
  onError: (message: string | null) => void;
  /** Whether a DJ's form is open, so the step isn't finished yet. */
  onEditing: (editing: boolean) => void;
};

/** Who's on it: one DJ, or a talk show's hosts. New DJs are made here, and DJs on it changed. */
export function DJStep({ draft, place, change, voices, known, stationId, onError, onEditing }: Props) {
  const talk = draft.kind === "talk";
  const [editing, setEditing] = useState<Editing | null>(null);
  const [full, setFull] = useState(false);
  const { hear, state } = useHear(onError);
  const picked = hostsOf(draft);

  useEffect(() => {
    onEditing(editing !== null);
  }, [editing, onEditing]);
  useEffect(() => () => onEditing(false), [onEditing]);

  // Every DJ to pick from: the office's, as they are on this station if they're on it, then new
  // ones made here.
  const cards: StationDJ[] = [
    ...known.map((profile) => draft.djs.find((dj) => dj.id === profile.id) ?? asStationDJ(profile)),
    ...draft.djs.filter((dj) => dj.id === null),
    ...draft.spare,
  ];
  const placeOf = (dj: StationDJ) => picked.findIndex((p) => keyOf(p) === keyOf(dj));
  const without = (key: string) => ({
    djs: draft.djs.filter((dj) => keyOf(dj) !== key),
    spare: draft.spare.filter((dj) => keyOf(dj) !== key),
  });

  /** Put `dj` on the station: after the others on a talk show, in place of the DJ otherwise.
   * New DJs taken off are kept to pick again. */
  const pick = (dj: StationDJ, rest: { djs: StationDJ[]; spare: StationDJ[] }) => {
    if (talk) {
      if (rest.djs.length >= MOST_DJS) {
        setFull(true);
        change({ djs: rest.djs, spare: dj.id === null ? [...rest.spare, dj] : rest.spare });
        return;
      }
      change({ djs: [...rest.djs, dj], spare: rest.spare });
      return;
    }
    const off = rest.djs.filter((other) => other.id === null);
    change({ djs: [dj], spare: [...rest.spare, ...off] });
  };

  const toggle = (dj: StationDJ) => {
    setFull(false);
    const key = keyOf(dj);
    const rest = without(key);
    if (placeOf(dj) >= 0) {
      // Taken off. On a station with a DJ, that's its one DJ.
      const djs = talk ? rest.djs : [];
      const off = talk ? [] : rest.djs.filter((other) => other.id === null);
      change({ djs, spare: [...rest.spare, ...off, ...(dj.id === null ? [dj] : [])] });
      return;
    }
    if (talk && !isEleven(dj.voice)) {
      setEditing({
        dj,
        key,
        reason: `${dj.name} has an OpenAI voice. A talk show needs ElevenLabs voices: pick one for ${dj.name} to bring them on.`,
      });
      return;
    }
    if (talk && picked.length >= MOST_DJS) {
      setFull(true);
      return;
    }
    pick(dj, rest);
  };

  const done = (dj: StationDJ) => {
    if (!editing) return;
    const was = editing.key;
    setEditing(null);
    if (was !== null) {
      const at = draft.djs.findIndex((other) => keyOf(other) === was);
      if (at >= 0 && placeOf(draft.djs[at]) >= 0) {
        // On the station already: changed where they are.
        change({ djs: draft.djs.map((other, index) => (index === at ? dj : other)) });
        return;
      }
    }
    pick(dj, was === null ? { djs: draft.djs, spare: draft.spare } : without(was));
  };

  const fresh = (): StationDJ => {
    // A talk show's DJs need ElevenLabs voices: one nobody on it has, if there is one.
    const eleven = voices?.elevenlabs.map((voice) => voice.id) ?? [];
    const free = eleven.find((id) => !picked.some((dj) => dj.voice === id)) ?? eleven[0];
    return {
      id: null,
      name: "",
      personality: "",
      voice: talk ? (free ?? "") : "marin",
      pet_peeves: "",
      soft_spots: "",
      obsession: "",
    };
  };

  if (editing) {
    const key = editing.key;
    const taken = cards
      .filter((dj) => keyOf(dj) !== key)
      .map((dj) => dj.name.trim().toLowerCase())
      .filter(Boolean);
    return (
      <StepBox place={place} lead={lead("djs", draft, place === "dialog")}>
        <DJForm
          initial={editing.dj}
          isNew={key === null}
          picks={key === null || placeOf(editing.dj) < 0}
          talk={talk}
          voices={voices}
          profile={known.find((profile) => profile.id === editing.dj.id)}
          stationId={stationId}
          taken={taken}
          reason={editing.reason}
          onDone={done}
          onCancel={() => setEditing(null)}
          onError={onError}
        />
      </StepBox>
    );
  }

  return (
    <StepBox place={place} lead={lead("djs", draft, place === "dialog")}>
      <div className={s.djs}>
        {cards.map((dj) => {
          const key = keyOf(dj);
          const at = placeOf(dj);
          const on = at >= 0;
          const profile = known.find((p) => p.id === dj.id);
          const others = elsewhere(profile, stationId);
          const here = stationId !== null && !!profile?.stations.some((st) => st.id === stationId);
          const where =
            dj.id === null
              ? "New, made when the station's saved"
              : others.length > 0
                ? `${here ? "Also hosts" : "Hosts"} ${listed(others)}`
                : here
                  ? "Only on this station"
                  : "On no station yet";
          const openai = talk && !isEleven(dj.voice);
          const hearing = state(key);
          return (
            <div key={key} className={`${s.dj} ${on ? s.on : ""}`}>
              <button type="button" aria-pressed={on} className={s.djPick} onClick={() => toggle(dj)}>
                <Avatar dj={dj} badge={on ? (talk ? at + 1 : "tick") : undefined} />
                <span className={s.djText}>
                  <span className={s.djName}>{dj.name}</span>
                  <span className={s.djAbout}>{dj.personality || "No personality yet."}</span>
                  <span className={s.djWhere}>{where}</span>
                  {openai && (
                    <span className={s.djProblem}>
                      {on
                        ? "OpenAI voice: Change it to an ElevenLabs one."
                        : "OpenAI voice: pick to give them an ElevenLabs one."}
                    </span>
                  )}
                </span>
              </button>
              <div className={s.djSide}>
                <button
                  type="button"
                  className={s.sideButton}
                  aria-label={hearing === "idle" ? `Hear ${dj.name}` : `${hearLabel(hearing)}, ${dj.name}`}
                  onClick={() => hear(key, dj)}
                >
                  <Icon name={hearing === "playing" ? "stop" : "headphones"} size={18} />
                  {hearLabel(hearing)}
                </button>
                {on && (
                  <button
                    type="button"
                    className={s.sideButton}
                    aria-label={`Change ${dj.name}`}
                    onClick={() => setEditing({ dj, key })}
                  >
                    <Icon name="edit" size={18} />
                    Change
                  </button>
                )}
              </div>
            </div>
          );
        })}
        <button
          type="button"
          className={s.newDJ}
          onClick={() => {
            setFull(false);
            setEditing({ dj: fresh(), key: null });
          }}
        >
          <Icon name="plus" size={20} strokeWidth={2.2} />
          New DJ
        </button>
      </div>
      <p className={s.hint} role={full ? "status" : undefined}>
        {full
          ? "That's six, the most a show can have. Take one off to pick another."
          : talk
            ? `Picked ${picked.length} of up to six. Changing a DJ changes them on every station they host.`
            : "Changing a DJ changes them on every station they host."}
      </p>
    </StepBox>
  );
}
