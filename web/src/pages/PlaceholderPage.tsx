import styles from "./Page.module.css";

type Props = {
  title: string;
  stage: number;
};

/** Stands in for a screen that a later stage of dev.md builds. */
export function PlaceholderPage({ title, stage }: Props) {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>{title}</h1>
      </header>
      <section className={styles.empty}>
        <p className={styles.emptyText}>Not built yet. This screen arrives in stage {stage}.</p>
      </section>
    </div>
  );
}
