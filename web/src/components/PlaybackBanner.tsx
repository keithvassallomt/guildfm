import type { PlaybackState } from "../api";
import { opensAgain } from "../live/status";
import styles from "./PlaybackBanner.module.css";

type Props = {
  playback: PlaybackState | null;
  /** The viewer can press Play, so it says what pressing it does. */
  canPlay?: boolean;
};

/** Why there's no music, when there isn't: stopped, outside playback hours, taken over, or
 * the speakers not answering. */
export function PlaybackBanner({ playback, canPlay = false }: Props) {
  const messages: Partial<Record<string, [string, string]>> = canPlay
    ? {
        stopped: ["The music is stopped", "Press Play to start it again."],
        overridden: [
          "Someone's playing something from the Sonos app",
          "GuildFM has stepped aside, announcements included. Press Play to take the speakers back.",
        ],
        offline: ["Can't reach the speakers", playback?.error ?? "Check they're switched on."],
      }
    : {
        stopped: ["The music is stopped", "Requests still queue up, and play once it starts again."],
        overridden: [
          "Someone's playing something from the Sonos app",
          "GuildFM carries on when someone takes the speakers back.",
        ],
        offline: ["Can't reach the speakers", "Requests still queue up in the meantime."],
      };
  if (playback?.status === "stopped" && playback.hours?.open === false) {
    messages.stopped = [
      "Outside playback hours",
      canPlay
        ? `${opensAgain(playback.hours)} Pressing Play overrides that, until Stop or the next closing time.`
        : `${opensAgain(playback.hours)} Requests still queue up until then.`,
    ];
  }
  const message = playback && messages[playback.status];
  if (!message) return null;
  return (
    <div
      className={`${styles.banner} ${playback.status === "stopped" ? "" : styles.warn}`}
      role="status"
    >
      <strong>{message[0]}</strong>
      {message[1]}
    </div>
  );
}
