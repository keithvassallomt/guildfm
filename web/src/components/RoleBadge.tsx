import type { Role } from "../api";
import styles from "./RoleBadge.module.css";

const labels: Record<Role, string> = { user: "User", curator: "Curator", admin: "Admin" };

export function RoleBadge({ role }: { role: Role }) {
  return <span className={`${styles.badge} ${styles[role]}`}>{labels[role]}</span>;
}

export const roleOptions = (Object.keys(labels) as Role[]).map((role) => ({
  value: role,
  label: labels[role],
}));
