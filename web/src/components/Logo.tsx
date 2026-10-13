import styles from "./Logo.module.css";

export function Logo() {
  return (
    <span className={styles.logo}>
      <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
        <circle cx="14" cy="14" r="12" fill="none" stroke="currentColor" strokeWidth="2" />
        <path d="M14 14L20 7" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
        <circle cx="14" cy="14" r="2.5" fill="currentColor" />
      </svg>
      <span className={styles.name}>GuildFM</span>
    </span>
  );
}
