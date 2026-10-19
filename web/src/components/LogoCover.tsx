import { Logo } from "./Logo";
import styles from "./LogoCover.module.css";

/** GuildFM's logo where a song's cover would go, while GuildFM's own sound is on: an
 * announcement, the DJ or a jingle. `className` gives it the cover's size and shape. */
export function LogoCover({ className }: { className: string }) {
  return (
    <span className={`${className} ${styles.cover}`}>
      <Logo className={styles.mark} />
    </span>
  );
}
