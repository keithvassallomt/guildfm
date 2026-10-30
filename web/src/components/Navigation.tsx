import { Fragment } from "react";
import { NavLink } from "react-router";
import type { Permission } from "../api";
import { useAuth } from "../auth/AuthProvider";
import { useVersion } from "../live/useVersion";
import { Icon, type IconName } from "./Icon";
import { Logo } from "./Logo";
import styles from "./Navigation.module.css";
import { useWide } from "./useWide";

type Page = { to: string; label: string; needs?: Permission };

type Tab = Page & {
  /** The label in the phone tab bar, when the full one is too long. */
  short?: string;
  icon: IconName;
  /** Only in the sidebar. On phones it's the avatar on Now Playing, keeping the tabs to five. */
  wideOnly?: boolean;
  /** Pages listed under it in the sidebar. On phones they're links on its own page. */
  under?: Page[];
};

const tabs: Tab[] = [
  { to: "/", label: "Now Playing", short: "Now", icon: "now" },
  { to: "/queue", label: "Queue", icon: "queue" },
  { to: "/playlists", label: "Playlists", icon: "library", needs: "switch_source" },
  { to: "/radio", label: "Radio", icon: "radio", needs: "switch_source" },
  // On phones it's reached from Now Playing's Line-ups tab, keeping the tabs to five.
  { to: "/lineups", label: "Line-ups", icon: "lineups", needs: "switch_source", wideOnly: true },
  {
    to: "/admin",
    label: "Admin",
    icon: "admin",
    needs: "control_playback",
    under: [
      { to: "/admin/announcements", label: "Announcements", needs: "announce" },
      { to: "/admin/jingles", label: "Jingles", needs: "change_settings" },
      { to: "/admin/users", label: "Users", needs: "manage_users" },
      { to: "/admin/settings", label: "Settings", needs: "change_settings" },
      { to: "/admin/status", label: "Status", needs: "change_settings" },
    ],
  },
  { to: "/profile", label: "Profile", icon: "profile", wideOnly: true },
];

/** A tab bar along the bottom on phones, a sidebar on wider screens. */
export function Navigation() {
  const { can } = useAuth();
  const wide = useWide();
  const version = useVersion();
  const allowed = (page: Page) => !page.needs || can(page.needs);

  return (
    <nav aria-label="Main" className={styles.nav}>
      <div className={styles.brand}>
        <Logo />
      </div>
      <div className={styles.links}>
        {tabs.filter(allowed).map((tab) => {
          const under = (tab.under ?? []).filter(allowed);
          return (
            <Fragment key={tab.to}>
              <NavLink
                to={tab.to}
                // In the sidebar, a page listed under it lights up instead.
                end={tab.to === "/" || (wide && under.length > 0)}
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
              {wide &&
                under.map((page) => (
                  <NavLink
                    key={page.to}
                    to={page.to}
                    className={({ isActive }) => `${styles.under} ${isActive ? styles.underActive : ""}`}
                  >
                    {page.label}
                  </NavLink>
                ))}
            </Fragment>
          );
        })}
      </div>
      {/* At the foot of the sidebar. On phones it's on Profile, keeping the tabs to five. */}
      <NavLink
        to="/help"
        className={({ isActive }) =>
          `${styles.link} ${styles.wideOnly} ${styles.help} ${isActive ? styles.active : ""}`
        }
      >
        <Icon name="help" />
        Help
      </NavLink>
      {version && <p className={`${styles.wideOnly} ${styles.version}`}>GuildFM {version}</p>}
    </nav>
  );
}
