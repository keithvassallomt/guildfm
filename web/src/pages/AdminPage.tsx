import { Link } from "react-router";
import { useAuth } from "../auth/AuthProvider";
import { Icon, type IconName } from "../components/Icon";
import { StatusChip } from "../components/StatusChip";
import { chipLabel, statusTones } from "../live/status";
import { usePlayback } from "../live/usePlayback";
import type { Permission } from "../api";
import admin from "./AdminPage.module.css";
import styles from "./Page.module.css";

type Place = { to: string; icon: IconName; title: string; hint: string; needs: Permission };

const PLACES: Place[] = [
  {
    to: "/admin/announcements",
    icon: "announce",
    title: "Announcements",
    hint: "Say something on the speakers, now or on a schedule",
    needs: "announce",
  },
  {
    to: "/admin/jingles",
    icon: "jingle",
    title: "Jingles",
    hint: "System idents, played between songs on any AI station",
    needs: "change_settings",
  },
  {
    to: "/admin/users",
    icon: "users",
    title: "Users",
    hint: "Accounts, roles and password resets",
    needs: "manage_users",
  },
  {
    to: "/admin/settings",
    icon: "admin",
    title: "Settings",
    hint: "Playback hours, voting rules, voices and connections",
    needs: "change_settings",
  },
  {
    to: "/admin/status",
    icon: "status",
    title: "Status",
    hint: "The speakers and services GuildFM needs, backups and recent problems",
    needs: "change_settings",
  },
];

/** Where admins manage GuildFM. The playback controls are on Now Playing. */
export function AdminPage() {
  const { can } = useAuth();
  const { state } = usePlayback();

  return (
    <div className={`${styles.page} ${styles.narrow}`}>
      <header className={styles.header}>
        <h1 className={styles.title}>Admin</h1>
        {state && <StatusChip tone={statusTones[state.status]}>{chipLabel(state)}</StatusChip>}
      </header>

      <nav aria-label="Admin" className={admin.links}>
        {PLACES.filter((place) => can(place.needs)).map((place) => (
          <Link key={place.to} to={place.to} className={admin.link}>
            <Icon name={place.icon} />
            <span className={admin.linkText}>
              <span className={admin.linkTitle}>{place.title}</span>
              <span className={admin.linkHint}>{place.hint}</span>
            </span>
            <Icon name="chevronRight" size={18} />
          </Link>
        ))}
      </nav>

      <p className={styles.muted}>
        Play, pause, Stop all and the volume of each room are on{" "}
        <Link to="/">Now Playing</Link>, as is a quick announcement.
      </p>
    </div>
  );
}
