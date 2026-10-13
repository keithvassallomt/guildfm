import { Link } from "react-router";
import { Icon } from "../components/Icon";
import admin from "./AdminPage.module.css";
import styles from "./Page.module.css";

export function AdminPage() {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Admin</h1>
      </header>

      <div className={styles.columns}>
        <section className={styles.section} aria-labelledby="playback">
          <h2 id="playback" className={styles.sectionTitle}>
            Playback
          </h2>
          <div className={styles.card}>
            <p className={styles.muted}>
              Play, pause, skip, stop and volume controls arrive in stage 3.
            </p>
          </div>
        </section>

        <section className={styles.section} aria-labelledby="manage">
          <h2 id="manage" className={styles.sectionTitle}>
            Manage
          </h2>
          <nav aria-labelledby="manage" className={admin.links}>
            <Link to="/admin/users" className={admin.link}>
              <Icon name="users" />
              <span className={admin.linkText}>
                <span className={admin.linkTitle}>Users</span>
                <span className={admin.linkHint}>Accounts, roles and password resets</span>
              </span>
              <Icon name="chevronRight" size={18} />
            </Link>
          </nav>
        </section>
      </div>
    </div>
  );
}
