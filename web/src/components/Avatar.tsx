import type { CSSProperties } from "react";
import styles from "./Avatar.module.css";

type Props = {
  name: string;
  size?: number;
  strong?: boolean;
};

/** A circle with someone's initial. Decorative, since their name is always shown beside it. */
export function Avatar({ name, size = 40, strong = false }: Props) {
  return (
    <span
      aria-hidden="true"
      className={`${styles.avatar} ${strong ? styles.strong : ""}`}
      style={{ "--size": `${size}px` } as CSSProperties}
    >
      {name.trim().charAt(0).toUpperCase()}
    </span>
  );
}
