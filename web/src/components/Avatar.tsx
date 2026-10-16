import type { CSSProperties } from "react";
import styles from "./Avatar.module.css";

type Props = {
  name: string;
  /** Their photo; their initial without one. */
  url?: string | null;
  size?: number;
  strong?: boolean;
  /** Sits in a line of text, before a name. */
  inline?: boolean;
};

/** A circle with someone's photo or initial. Decorative, since their name is always shown
 * beside it. */
export function Avatar({ name, url, size = 40, strong = false, inline = false }: Props) {
  const placed = inline ? styles.inline : "";
  if (url) {
    return (
      <img
        src={url}
        alt=""
        className={`${styles.avatar} ${styles.photo} ${placed}`}
        style={{ "--size": `${size}px` } as CSSProperties}
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      className={`${styles.avatar} ${strong ? styles.strong : ""} ${placed}`}
      style={{ "--size": `${size}px` } as CSSProperties}
    >
      {name.trim().charAt(0).toUpperCase()}
    </span>
  );
}
