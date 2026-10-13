import { useCallback, useEffect, useRef, useState } from "react";
import styles from "./Toast.module.css";

const SHOWN_MS = 2600;

/** A short message that fades after a moment, read out by screen readers. */
export function useToast() {
  const [message, setMessage] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const show = useCallback((text: string) => {
    setMessage(text);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMessage(null), SHOWN_MS);
  }, []);

  const toast = (
    <div role="status" className={`${styles.toast} ${message ? styles.shown : ""}`}>
      {message}
    </div>
  );
  return { show, toast };
}
