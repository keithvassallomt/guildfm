import { type CSSProperties, type ReactNode, useLayoutEffect, useRef, useState } from "react";
import styles from "./Marquee.module.css";

const SPEED = 30; // pixels a second
const MOVING = 0.7; // the share of each pass spent moving; the rest is a pause at either end

type Props = {
  children: ReactNode;
  className?: string;
};

/** One line of text that scrolls back and forth when it's too long to fit. */
export function Marquee({ children, className = "" }: Props) {
  const box = useRef<HTMLSpanElement>(null);
  const text = useRef<HTMLSpanElement>(null);
  const [overflow, setOverflow] = useState(0);

  useLayoutEffect(() => {
    if (!box.current || !text.current) return;
    const outer = box.current;
    const inner = text.current;
    // offsetWidth ignores the scrolling transform, so measuring mid-scroll is fine.
    const measure = () => setOverflow(Math.max(0, inner.offsetWidth - outer.clientWidth));
    measure();
    // Also catches the first real layout, since a dialog's content is measured before it opens.
    const observer = new ResizeObserver(measure);
    observer.observe(outer);
    observer.observe(inner);
    return () => observer.disconnect();
  }, []);

  const scrolling = overflow > 0;
  const style = scrolling
    ? ({
        "--marquee-shift": `-${overflow}px`,
        "--marquee-time": `${Math.max(3, overflow / SPEED / MOVING)}s`,
      } as CSSProperties)
    : undefined;

  return (
    <span ref={box} className={`${styles.marquee} ${scrolling ? styles.scrolling : ""} ${className}`}>
      <span ref={text} className={styles.text} style={style}>
        {children}
      </span>
    </span>
  );
}
