import { ButtonLink } from "../components/Button";
import { Icon } from "../components/Icon";
import { Logo } from "../components/Logo";
import { StatusChip } from "../components/StatusChip";
import { useLive } from "../live/LiveProvider";
import styles from "./Page.module.css";

export function QueuePage() {
  const { connected } = useLive();

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1>
          <Logo />
        </h1>
        <StatusChip tone={connected ? "live" : "idle"}>
          {connected ? "Connected" : "Offline"}
        </StatusChip>
      </header>

      <section className={styles.empty} aria-labelledby="empty-queue">
        <h2 id="empty-queue" className={styles.emptyTitle}>
          The queue is empty
        </h2>
        <p className={styles.emptyText}>Find a song in Search to get things going.</p>
        <ButtonLink to="/search">
          <Icon name="plus" size={18} strokeWidth={2.6} />
          Request a song
        </ButtonLink>
      </section>
    </div>
  );
}
