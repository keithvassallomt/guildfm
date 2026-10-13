import { type FormEvent, useState } from "react";
import { errorText } from "../api";
import { useAuth, useMe } from "../auth/AuthProvider";
import { useQueue } from "../live/useQueue";
import { Avatar } from "../components/Avatar";
import { Button, ButtonLink } from "../components/Button";
import { RoleBadge } from "../components/RoleBadge";
import { FormError, TextField } from "../components/TextField";
import { Toggle } from "../components/Toggle";
import styles from "./Page.module.css";
import profile from "./ProfilePage.module.css";

export function ProfilePage() {
  const me = useMe();
  const { updateProfile, signOut } = useAuth();
  const [name, setName] = useState(me.display_name);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const shownName = name.trim() || me.display_name;
  const nameChanged = name.trim() !== me.display_name;

  const saveName = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await updateProfile({ display_name: name });
      setSaved(true);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  };

  const setAnnounce = async (announce: boolean) => {
    setError(null);
    try {
      await updateProfile({ announce_requests: announce });
    } catch (caught) {
      setError(errorText(caught));
    }
  };

  return (
    <div className={styles.page}>
      <header className={profile.identity}>
        <Avatar name={shownName} size={64} strong />
        <div className={profile.who}>
          <h1 className={styles.title}>{me.display_name}</h1>
          <div className={profile.handle}>
            @{me.username}
            <RoleBadge role={me.role} />
          </div>
        </div>
      </header>

      <div className={styles.columns}>
        <section className={styles.card} aria-labelledby="on-air">
          <h2 id="on-air" className={styles.sectionTitle}>
            On air
          </h2>
          <form className={profile.nameForm} onSubmit={saveName}>
            <TextField
              label="Display name"
              value={name}
              maxLength={40}
              autoComplete="nickname"
              onChange={(event) => {
                setName(event.target.value);
                setSaved(false);
              }}
            />
            <Button type="submit" variant="secondary" disabled={busy || !nameChanged}>
              {saved && !nameChanged ? "Saved" : "Save"}
            </Button>
          </form>
          <div className={profile.toggleRow}>
            <div className={profile.toggleText}>
              <span id="announce-label" className={profile.toggleLabel}>
                Announce my requests
              </span>
              <span className={styles.muted}>
                The DJ can say your name when it plays a song you asked for.
              </span>
            </div>
            <Toggle
              checked={me.announce_requests}
              onChange={setAnnounce}
              labelledBy="announce-label"
            />
          </div>
          <div className={profile.sample}>
            <span className={profile.sampleLabel}>How it sounds</span>
            {me.announce_requests
              ? `"This next one goes out to ${shownName}. Here's MGMT with Electric Feel."`
              : `"Here's MGMT with Electric Feel." Your name stays off air.`}
          </div>
          <FormError message={error} />
        </section>

        <div className={styles.stack}>
          <section className={styles.section} aria-labelledby="mine">
            <h2 id="mine" className={styles.sectionTitle}>
              Your requests
            </h2>
            <YourRequests />
          </section>

          <section className={styles.section} aria-labelledby="account">
            <h2 id="account" className={styles.sectionTitle}>
              Account
            </h2>
            <div className={styles.card}>
              <p className={styles.muted}>To change your password, ask an admin to reset it.</p>
              <Button variant="secondary" onClick={() => signOut()}>
                Sign out
              </Button>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function YourRequests() {
  const { queue } = useQueue();
  if (!queue) return null;

  const mine = [
    ...(queue.playing?.mine ? [{ entry: queue.playing, where: "Playing now" }] : []),
    ...(queue.next?.mine ? [{ entry: queue.next, where: "Up next" }] : []),
    ...queue.waiting.flatMap((entry, index) =>
      entry.mine ? [{ entry, where: `Number ${index + 1} in the queue` }] : [],
    ),
  ];

  return (
    <div className={styles.card}>
      {mine.length === 0 ? (
        <p className={styles.muted}>Nothing requested yet.</p>
      ) : (
        <ul className={profile.requests}>
          {mine.map(({ entry, where }) => (
            <li key={entry.id} className={profile.request}>
              {entry.track.art_url ? (
                <img src={entry.track.art_url} alt="" className={profile.art} />
              ) : (
                <span aria-hidden="true" className={profile.art} />
              )}
              <span className={profile.requestText}>
                <span className={profile.requestTitle}>{entry.track.title}</span>
                <span className={styles.muted}>
                  {entry.track.artists} · {where}
                </span>
              </span>
              <span className={profile.score}>{entry.score > 0 ? `+${entry.score}` : entry.score}</span>
            </li>
          ))}
        </ul>
      )}
      <p className={styles.muted}>
        {queue.mine} of {queue.request_cap} requests in use.
      </p>
      <ButtonLink to="/search" variant="secondary">
        Find a song
      </ButtonLink>
    </div>
  );
}
