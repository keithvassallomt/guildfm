import { NavLink } from "react-router";
import type { Permission } from "../api";
import { useAuth } from "../auth/AuthProvider";
import { Icon, type IconName } from "./Icon";
import { Logo } from "./Logo";
import styles from "./Navigation.module.css";

type Tab = {
  to: string;
  label: string;
  /** The label in the phone tab bar, when the full one is too long. */
  short?: string;
  icon: IconName;
  needs?: Permission;
  /** Only in the sidebar. On phones it's the avatar on Now Playing, keeping the tabs to five. */
  wideOnly?: boolean;
};

const tabs: Tab[] = [
  { to: "/", label: "Now Playing", short: "Now", icon: "now" },
  { to: "/queue", label: "Queue", icon: "queue" },
  { to: "/search", label: "Search", icon: "search" },
  { to: "/library", label: "Library", icon: "library", needs: "switch_source" },
  { to: "/admin", label: "Admin", icon: "admin", needs: "control_playback" },
  { to: "/profile", label: "Profile", icon: "profile", wideOnly: true },
];

/** A tab bar along the bottom on phones, a sidebar on wider screens. */
export function Navigation() {
  const { can } = useAuth();

  return (
    <nav aria-label="Main" className={styles.nav}>
      <div className={styles.brand}>
        <Logo />
      </div>
      <div className={styles.links}>
        {tabs
          .filter((tab) => !tab.needs || can(tab.needs))
          .map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to}
              end={tab.to === "/"}
              className={({ isActive }) =>
                `${styles.link} ${isActive ? styles.active : ""} ${tab.wideOnly ? styles.wideOnly : ""}`
              }
            >
              <Icon name={tab.icon} />
              {tab.short ? (
                <>
                  <span className={styles.long}>{tab.label}</span>
                  <span className={styles.short}>{tab.short}</span>
                </>
              ) : (
                tab.label
              )}
            </NavLink>
          ))}
      </div>
    </nav>
  );
}
