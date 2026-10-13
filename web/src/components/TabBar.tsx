import { NavLink } from "react-router";
import { Icon, type IconName } from "./Icon";
import styles from "./TabBar.module.css";

const tabs: { to: string; label: string; icon: IconName }[] = [
  { to: "/", label: "Queue", icon: "queue" },
  { to: "/search", label: "Search", icon: "search" },
  { to: "/library", label: "Library", icon: "library" },
  { to: "/admin", label: "Admin", icon: "admin" },
  { to: "/profile", label: "Profile", icon: "profile" },
];

export function TabBar() {
  return (
    <nav aria-label="Main" className={styles.bar}>
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end={tab.to === "/"}
          className={({ isActive }) => `${styles.tab} ${isActive ? styles.active : ""}`}
        >
          <Icon name={tab.icon} />
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}
