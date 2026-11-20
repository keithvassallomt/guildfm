import { type ReactNode, type Ref, useCallback, useId, useState } from "react";
import { errorText, type StationDJ } from "../api";
import { Icon } from "../components/Icon";
import { usePreview } from "../components/PreviewButton";
import { Toggle } from "../components/Toggle";
import { djColour, sampleLine } from "./kinds";
import s from "./Steps.module.css";

/** Which step a piece of UI is in: the wizard's page, or a Change dialog on the station's. */
export type Place = "wizard" | "dialog";

/** A step's outer box, with its line of explanation at the top in a dialog. */
export function StepBox({ place, lead, children }: { place: Place; lead?: string; children: ReactNode }) {
  return (
    <div className={`${s.step} ${place === "dialog" ? s.inDialog : ""}`}>
      {place === "dialog" && lead && <p className={s.lead}>{lead}</p>}
      {children}
    </div>
  );
}

type AreaProps = {
  label: string;
  value: string;
  rows: number;
  placeholder?: string;
  maxLength?: number;
  /** Shows how much of `maxLength` is used, beside the label. */
  counted?: boolean;
  hint?: ReactNode;
  textareaRef?: Ref<HTMLTextAreaElement>;
  onChange: (value: string) => void;
};

export function Area({
  label,
  value,
  rows,
  placeholder,
  maxLength = 600,
  counted,
  hint,
  textareaRef,
  onChange,
}: AreaProps) {
  const id = useId();
  const hintId = useId();
  return (
    <div className={s.field}>
      <span className={s.labelRow}>
        <label htmlFor={id} className={s.label}>
          {label}
        </label>
        {counted && (
          <span className={s.count}>
            {value.length} / {maxLength}
          </span>
        )}
      </span>
      <textarea
        ref={textareaRef}
        id={id}
        rows={rows}
        maxLength={maxLength}
        value={value}
        placeholder={placeholder}
        aria-describedby={hint ? hintId : undefined}
        onChange={(event) => onChange(event.target.value)}
        className={s.textarea}
      />
      {hint && (
        <span id={hintId} className={s.hint}>
          {hint}
        </span>
      )}
    </div>
  );
}

type SwitchRowProps = {
  label: string;
  hint?: string;
  checked: boolean;
  className?: string;
  onChange: (checked: boolean) => void;
};

export function SwitchRow({ label, hint, checked, className, onChange }: SwitchRowProps) {
  const id = useId();
  return (
    <div className={`${s.row} ${className ?? ""}`}>
      <span className={s.rowText}>
        <span id={id} className={s.rowLabel}>
          {label}
        </span>
        {hint && <span className={s.rowHint}>{hint}</span>}
      </span>
      <Toggle checked={checked} onChange={onChange} labelledBy={id} />
    </div>
  );
}

/** A DJ's initial in their colour, with their place on a show or a tick. */
export function Avatar({
  dj,
  badge,
  small,
}: {
  dj: { id: number | null; name: string };
  badge?: number | "tick";
  small?: boolean;
}) {
  return (
    <span
      className={`${s.avatar} ${small ? s.small : ""}`}
      style={{ background: djColour(dj) }}
      aria-hidden="true"
    >
      {(dj.name.trim() || "?").charAt(0).toUpperCase()}
      {badge !== undefined && (
        <span className={s.badge}>{badge === "tick" ? <Icon name="check" size={12} strokeWidth={3.4} /> : badge}</span>
      )}
    </span>
  );
}

/** Hearing DJs on this device, one at a time: a line in their voice and personality. */
export function useHear(onError: (message: string | null) => void) {
  const { status, play, stop } = usePreview();
  const [who, setWho] = useState<string | null>(null);

  const hear = useCallback(
    (key: string, dj: Pick<StationDJ, "name" | "personality" | "voice">, text?: string) => {
      if (who === key && status !== "idle") {
        stop();
        return;
      }
      onError(null);
      setWho(key);
      play("/stations/preview", {
        text: text ?? sampleLine(dj.voice),
        voice: dj.voice,
        dj_name: dj.name,
        personality: dj.personality,
      }).catch((caught) => onError(errorText(caught)));
    },
    [who, status, play, stop, onError],
  );

  /** How hearing `key` is going. */
  const state = (key: string) => (who === key ? status : "idle");
  return { hear, state };
}

export const hearLabel = (state: "idle" | "loading" | "playing") =>
  state === "loading" ? "Wait" : state === "playing" ? "Stop" : "Hear";
