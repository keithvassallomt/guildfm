import { type KeyboardEvent, useRef } from "react";
import styles from "./ChoiceCards.module.css";

type Choice<T extends string> = { value: T; label: string; hint: string };

type Props<T extends string> = {
  label: string;
  choices: Choice<T>[];
  value: T;
  onChange: (value: T) => void;
};

/** One choice from a few, each with a line of explanation. Arrow keys move between them. */
export function ChoiceCards<T extends string>({ label, choices, value, onChange }: Props<T>) {
  const cards = useRef<(HTMLButtonElement | null)[]>([]);

  const onKeyDown = (event: KeyboardEvent, index: number) => {
    const step = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const next = (index + step + choices.length) % choices.length;
    onChange(choices[next].value);
    cards.current[next]?.focus();
  };

  return (
    <div role="radiogroup" aria-label={label} className={styles.cards}>
      {choices.map((choice, index) => (
        <button
          key={choice.value}
          ref={(element) => {
            cards.current[index] = element;
          }}
          type="button"
          role="radio"
          aria-checked={choice.value === value}
          tabIndex={choice.value === value ? 0 : -1}
          className={styles.card}
          onClick={() => onChange(choice.value)}
          onKeyDown={(event) => onKeyDown(event, index)}
        >
          <span className={styles.label}>{choice.label}</span>
          <span className={styles.hint}>{choice.hint}</span>
        </button>
      ))}
    </div>
  );
}
