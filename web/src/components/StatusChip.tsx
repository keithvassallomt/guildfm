import type { ReactNode } from "react";
import styles from "./StatusChip.module.css";

type Props = {
  tone: "live" | "idle" | "warn";
  children: ReactNode;
};

export function StatusChip({ tone, children }: Props) {
  return (
    <span className={styles.chip}>
      <span className={`${styles.dot} ${styles[tone]}`} />
      {children}
    </span>
  );
}
