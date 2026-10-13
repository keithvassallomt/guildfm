import styles from "./Toggle.module.css";

type Props = {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** Id of the visible text that names this switch. */
  labelledBy: string;
  disabled?: boolean;
};

export function Toggle({ checked, onChange, labelledBy, disabled }: Props) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-labelledby={labelledBy}
      disabled={disabled}
      className={styles.toggle}
      onClick={() => onChange(!checked)}
    >
      <span className={styles.track}>
        <span className={styles.knob} />
      </span>
    </button>
  );
}
