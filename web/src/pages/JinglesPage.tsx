import { useEffect, useId, useState } from "react";
import { Link } from "react-router";
import { api, errorText, type SettingsState } from "../api";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import { JingleList } from "../components/JingleList";
import { FormError } from "../components/TextField";
import styles from "./Page.module.css";
import j from "./JinglesPage.module.css";

/** The system idents, GuildFM's own, which any AI station can play between songs. */
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

      <section className={styles.section} aria-labelledby="system-idents">
        <h2 id="system-idents" className={styles.sectionTitle}>
          System idents
        </h2>
        <div className={styles.card}>
          <JingleList
            stationId={null}
            empty="None yet. System idents are GuildFM's own, for every AI station."
          />
        </div>
      </section>

      <About />

      <p className={styles.muted}>
        Station idents belong to one station. Add or generate them in the station's editor,
        under <Link to="/radio">Radio</Link>.
      </p>
    </div>
  );
}

/** What GuildFM is, for the AI writing system idents in the jingle generator. */
function About() {
  const id = useId();
  const [saved, setSaved] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<SettingsState>("GET", "/settings")
      .then((settings) => {
        setSaved(settings.values.about);
        setText(settings.values.about);
      })
      .catch((caught) => setError(errorText(caught)));
  }, []);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const settings = await api<SettingsState>("PATCH", "/settings", { about: text });
      setSaved(settings.values.about);
      setText(settings.values.about);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setSaving(false);
    }
  };

  const changed = saved !== null && text.trim() !== saved;
  return (
    <section className={styles.section} aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`} className={styles.sectionTitle}>
        About GuildFM
      </h2>
      <div className={styles.card}>
        <label htmlFor={id} className={styles.muted}>
          What GuildFM is, who listens and how it should sound. The AI reads this when it writes
          system idents.
        </label>
        <textarea
          id={id}
          rows={4}
          maxLength={1000}
          value={text}
          disabled={saved === null}
          onChange={(event) => setText(event.target.value)}
          className={j.about}
        />
        <div className={j.save}>
          <Button variant="secondary" disabled={!changed || !text.trim() || saving} onClick={save}>
            {saving ? "Saving..." : changed ? "Save" : "Saved"}
          </Button>
        </div>
        <FormError message={error} />
      </div>
    </section>
  );
}
