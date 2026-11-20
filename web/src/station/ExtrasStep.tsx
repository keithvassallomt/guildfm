import { Icon } from "../components/Icon";
import { type Draft, lead } from "./kinds";
import { type Place, StepBox, SwitchRow } from "./parts";
import s from "./Steps.module.css";

type Props = {
  draft: Draft;
  place: Place;
  change: (changes: Partial<Draft>) => void;
};

/** Jingles, crossfading and knowing what's going on. */
export function ExtrasStep({ draft, place, change }: Props) {
  const made = place === "dialog";
  return (
    <StepBox place={place} lead={lead("extras", draft, made)}>
      <div className={s.switches}>
        <SwitchRow
          label="Play jingles"
          hint={
            made
              ? "GuildFM's idents and this station's own, in the pauses between songs."
              : "GuildFM's idents in the pauses between songs. Add the station's own once it's made."
          }
          checked={draft.jingles}
          onChange={(jingles) => change({ jingles })}
        />
        <SwitchRow
          label="Crossfade between songs"
          hint="Each song fades into the next, with no quiet gaps. The DJ and jingles fade in over the end of a song too."
          checked={draft.crossfade}
          onChange={(crossfade) => change({ crossfade })}
        />
        <SwitchRow
          label="Knows what's going on"
          hint="The time of day, the weather where the office is, and music news, like an artist's passing or a song contest winner."
          checked={draft.global_awareness}
          onChange={(global_awareness) => change({ global_awareness })}
        />
        {!made && (
          <div className={s.coverRow}>
            <span className={s.coverStandIn} aria-hidden="true">
              <Icon name="radio" size={26} />
            </span>
            <span className={s.rowText}>
              <span className={s.rowLabel}>Cover</span>
              <span className={s.rowHint}>
                Painted from its name and music once it's made. You can paint another any time.
              </span>
            </span>
          </div>
        )}
      </div>
    </StepBox>
  );
}
