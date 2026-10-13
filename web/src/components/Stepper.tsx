import { Icon } from "./Icon";
import styles from "./Stepper.module.css";

type Props = {
  /** Names the number for screen readers, such as "Requests per person". */
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
  disabled?: boolean;
};

/** A number with minus and plus buttons either side. */
export function Stepper({ label, value, min, max, step = 1, onChange, disabled }: Props) {
  return (
    <div className={styles.stepper} role="group" aria-label={label}>
      <button
        type="button"
        aria-label={`Less (${label})`}
        disabled={disabled || value <= min}
        onClick={() => onChange(Math.max(min, value - step))}
        className={styles.button}
      >
        <Icon name="minus" size={18} strokeWidth={2.4} />
      </button>
      <output className={styles.value} aria-live="polite">
        {value}
      </output>
      <button
        type="button"
        aria-label={`More (${label})`}
        disabled={disabled || value >= max}
        onClick={() => onChange(Math.min(max, value + step))}
        className={styles.button}
      >
        <Icon name="plus" size={18} strokeWidth={2.4} />
      </button>
    </div>
  );
}
