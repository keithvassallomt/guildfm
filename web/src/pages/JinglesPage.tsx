import { Link } from "react-router";
import { Icon } from "../components/Icon";
import { JingleList } from "../components/JingleList";
import styles from "./Page.module.css";

/** GuildFM's station idents, which any AI station can play between songs. */
export function JinglesPage() {
  return (
    <div className={`${styles.page} ${styles.narrow}`}>
      <header className={styles.header}>
        <div className={styles.headerStart}>
          <Link to="/admin" aria-label="Back to Admin" className={styles.iconLink}>
            <Icon name="back" />
          </Link>
          <h1 className={styles.title}>Jingles</h1>
        </div>
      </header>

      <p className={styles.muted}>
        AI stations play jingles in the pause between songs. The AI chooses where, and never
        plays two in a row. Playlists and announcements don't get them.
      </p>

      <section className={styles.section} aria-labelledby="station-idents">
        <h2 id="station-idents" className={styles.sectionTitle}>
          Station idents
        </h2>
        <div className={styles.card}>
          <JingleList
            stationId={null}
            empty="None yet. Station idents are GuildFM's own, for every AI station."
          />
        </div>
      </section>

      <p className={styles.muted}>
        Show idents belong to one station. Add them in the station's editor, under{" "}
        <Link to="/radio">Radio</Link>.
      </p>
    </div>
  );
}
