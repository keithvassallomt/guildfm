import { type InputHTMLAttributes, useId } from "react";
import styles from "./TextField.module.css";

type Props = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  hint?: string;
};

export function TextField({ label, hint, id, ...props }: Props) {
  const fallbackId = useId();
  const inputId = id ?? fallbackId;
  const hintId = `${inputId}-hint`;

  return (
    <div className={styles.field}>
      <label htmlFor={inputId} className={styles.label}>
        {label}
      </label>
      <input
        id={inputId}
        className={styles.input}
        aria-describedby={hint ? hintId : undefined}
        {...props}
      />
      {hint && (
        <span id={hintId} className={styles.hint}>
          {hint}
        </span>
      )}
    </div>
  );
}

/** A form-level message, read out by screen readers when it appears. */
export function FormError({ message }: { message: string | null }) {
  return (
    <p role="alert" className={styles.error}>
      {message}
    </p>
  );
}
