import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import styles from "./VolumeSlider.module.css";

type Props = {
  label: ReactNode;
  value: number;
  onCommit: (volume: number) => Promise<void>;
  disabled?: boolean;
  strong?: boolean;
};

const SEND_AFTER_MS = 250;

/**
 * A volume slider that follows the speakers, except while someone is dragging it.
 * Changes are sent a moment after the slider stops moving, not on every step.
 */
export function VolumeSlider({ label, value, onCommit, disabled, strong }: Props) {
  const id = useId();
  const [draft, setDraft] = useState<number | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const change = (next: number) => {
    setDraft(next);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      onCommit(next).finally(() => setDraft(null));
    }, SEND_AFTER_MS);
  };

  const shown = draft ?? value;
  return (
    <div className={`${styles.slider} ${strong ? styles.strong : ""}`}>
      <div className={styles.top}>
        <label htmlFor={id} className={styles.label}>
          {label}
        </label>
        <output htmlFor={id} className={styles.value}>
          {shown}
        </output>
      </div>
      <input
        id={id}
        type="range"
        min={0}
        max={100}
        value={shown}
        disabled={disabled}
        onChange={(event) => change(Number(event.target.value))}
        className={styles.range}
      />
    </div>
  );
}
