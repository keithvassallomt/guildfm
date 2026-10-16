import { type CSSProperties, type KeyboardEvent, type ReactNode, useRef } from "react";
import styles from "./SegmentedControl.module.css";

type Option<T extends string> = { value: T; label: ReactNode };

type Props<T extends string> = {
  label: string;
  options: Option<T>[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
};

/** A row of mutually exclusive choices. Arrow keys move between them, like radio buttons. */
export function SegmentedControl<T extends string>({
  label,
  options,
  value,
  onChange,
  disabled,
}: Props<T>) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  const onKeyDown = (event: KeyboardEvent, index: number) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const next = (index + step + options.length) % options.length;
    onChange(options[next].value);
    buttons.current[next]?.focus();
  };

  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={styles.group}
      style={{ "--count": options.length } as CSSProperties}
    >
      {options.map((option, index) => (
        <button
          key={option.value}
          ref={(element) => {
            buttons.current[index] = element;
          }}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          tabIndex={option.value === value ? 0 : -1}
          disabled={disabled}
          className={styles.option}
          onClick={() => onChange(option.value)}
          onKeyDown={(event) => onKeyDown(event, index)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
