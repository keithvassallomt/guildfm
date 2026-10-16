import type { RefObject } from "react";
import styles from "./EmotionPicker.module.css";

// ElevenLabs acts these out, changing how the words after the tag are said.
const EMOTIONS = [
  ["excited", "Excited"],
  ["cheerfully", "Cheerful"],
  ["laughs", "Laughs"],
  ["chuckles", "Chuckles"],
  ["whispers", "Whispers"],
  ["sighs", "Sighs"],
  ["sarcastic", "Sarcastic"],
  ["curious", "Curious"],
  ["mischievously", "Mischievous"],
  ["seriously", "Serious"],
] as const;

type Props = {
  className?: string;
  /** The text box the tag goes into, at its cursor. */
  textarea: RefObject<HTMLTextAreaElement | null>;
  text: string;
  maxLength: number;
  onText: (text: string) => void;
};

/** For an ElevenLabs voice: puts an emotion tag such as [excited] where the cursor is. */
export function EmotionPicker({ className = "", textarea, text, maxLength, onText }: Props) {
  const insert = (tag: string) => {
    const box = textarea.current;
    const at = box ? box.selectionStart : text.length;
    const before = text.slice(0, at);
    const added = `${before && !/\s$/.test(before) ? " " : ""}[${tag}] `;
    const next = before + added + text.slice(at).replace(/^\s+/, "");
    if (next.length > maxLength) return;
    onText(next);
    // Back to typing, just after the tag.
    window.requestAnimationFrame(() => {
      const cursor = (before + added).length;
      box?.focus();
      box?.setSelectionRange(cursor, cursor);
    });
  };

  return (
    <select
      aria-label="Add an emotion"
      value=""
      onChange={(event) => event.target.value && insert(event.target.value)}
      className={`${styles.picker} ${className}`}
    >
      <option value="">Add an emotion</option>
      {EMOTIONS.map(([tag, label]) => (
        <option key={tag} value={tag}>
          {label}
        </option>
      ))}
    </select>
  );
}
