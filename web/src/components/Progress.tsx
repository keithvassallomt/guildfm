import { useLayoutEffect, useRef, useState } from "react";
import type { PlaybackState } from "../api";
import { clock } from "../live/usePlayback";
import styles from "./Progress.module.css";

type Track = NonNullable<PlaybackState["track"]>;

// A report this far behind the bar means the song really went back, such as Previous starting
// it again. Anything less is the speakers rounding down and the report taking a moment.
const SNAP_SECONDS = 2;

type Anchor = { key: string; position: number; at: number; moving: boolean };

function positionAt(anchor: Anchor, now: number): number {
  return anchor.moving ? anchor.position + (now - anchor.at) / 1000 : anchor.position;
}

type Props = {
  track: Track;
  playing: boolean;
  /** When the state holding `track` arrived, from performance.now(). */
  receivedAt: number;
};

/** How far into the song the speakers are: a bar that glides along, and the times. */
export function Progress({ track, playing, receivedAt }: Props) {
  const fill = useRef<HTMLDivElement>(null);
  const anchor = useRef<Anchor | null>(null);
  const [seconds, setSeconds] = useState(() => Math.floor(track.position));

  useLayoutEffect(() => {
    // The speakers report whole seconds, rounded down, and a report takes a moment to arrive,
    // so each one is a lower bound. One ahead of the bar moves it on; one a little behind is
    // ignored, so the bar never steps back for nothing.
    const now = performance.now();
    const key = `${track.title}|${track.artist}|${track.duration}`;
    const reported = track.position + (playing ? (now - receivedAt) / 1000 : 0);
    const last = anchor.current;
    const shown = last ? positionAt(last, now) : 0;
    const lagging = reported <= shown && shown - reported <= SNAP_SECONDS;
    if (!(last && last.key === key && last.moving && playing && lagging)) {
      anchor.current = { key, position: reported, at: now, moving: playing };
    }

    let frame = 0;
    const draw = () => {
      const current = anchor.current;
      if (!current) return;
      const position = Math.min(track.duration, positionAt(current, performance.now()));
      if (fill.current) fill.current.style.transform = `scaleX(${position / track.duration})`;
      setSeconds(Math.floor(position));
      if (current.moving) frame = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(frame);
  }, [track, playing, receivedAt]);

  return (
    <div className={styles.progress}>
      <div className={styles.bar}>
        <div ref={fill} className={styles.fill} />
      </div>
      <div className={styles.times}>
        <span>{clock(seconds)}</span>
        <span>{clock(track.duration)}</span>
      </div>
    </div>
  );
}
