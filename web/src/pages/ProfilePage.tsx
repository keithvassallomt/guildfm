import { type FormEvent, useRef, useState } from "react";
import type { Area } from "react-easy-crop";
import { api, apiUpload, errorText, type Me } from "../api";
import { useAuth, useMe } from "../auth/AuthProvider";
import { useQueue } from "../live/useQueue";
import { Avatar } from "../components/Avatar";
import { Button, ButtonLink } from "../components/Button";
import { InstallApp } from "../components/InstallApp";
import { RoleBadge } from "../components/RoleBadge";
import { PhotoCropper } from "../components/PhotoCropper";
import { croppedPhoto, openPhoto } from "../components/photo";
import { FormError, TextField } from "../components/TextField";
import { Toggle } from "../components/Toggle";
import styles from "./Page.module.css";
import profile from "./ProfilePage.module.css";

export function ProfilePage() {
  const me = useMe();
  const { updateProfile, signOut, refresh } = useAuth();
  const [name, setName] = useState(me.display_name);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const photos = useRef<HTMLInputElement>(null);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoError, setPhotoError] = useState<string | null>(null);
  // The photo being cropped, before it's sent.
  const [cropping, setCropping] = useState<File | null>(null);
  const [cropError, setCropError] = useState<string | null>(null);

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

  /** Opens the chosen photo for cropping, once it's clear this browser can show it. */
  const choosePhoto = async (file: File | undefined) => {
    if (photos.current) photos.current.value = "";
    if (!file) return;
    setPhotoError(null);
    setCropError(null);
    try {
      (await openPhoto(file)).close();
      setCropping(file);
    } catch (caught) {
      setPhotoError(caught instanceof Error ? caught.message : errorText(caught));
    }
  };

  /** Shrinks the chosen part of the photo to a small square here, then sends it. */
  const savePhoto = async (area: Area) => {
    if (!cropping) return;
    setPhotoBusy(true);
    setCropError(null);
    try {
      await apiUpload<Me>("/me/avatar", await croppedPhoto(cropping, area));
      await refresh();
      setCropping(null);
    } catch (caught) {
      // A failed fetch is a TypeError; anything else here has a message fit to show.
      setCropError(
        caught instanceof Error && !(caught instanceof TypeError) ? caught.message : errorText(caught),
      );
    } finally {
      setPhotoBusy(false);
    }
  };

  const removePhoto = async () => {
    setPhotoError(null);
    try {
      await api<Me>("DELETE", "/me/avatar");
      await refresh();
    } catch (caught) {
      setPhotoError(errorText(caught));
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
        <Avatar name={shownName} url={me.avatar_url} size={64} strong />
        <div className={profile.who}>
          <h1 className={styles.title}>{me.display_name}</h1>
          <div className={profile.handle}>
            @{me.username}
            <RoleBadge role={me.role} />
          </div>
        </div>
      </header>

      <div className={profile.photo}>
        <input
          ref={photos}
          type="file"
          accept="image/*"
          hidden
          onChange={(event) => choosePhoto(event.target.files?.[0])}
        />
        <Button variant="secondary" disabled={photoBusy} onClick={() => photos.current?.click()}>
          {photoBusy ? "Adding..." : me.avatar_url ? "Change photo" : "Add a photo"}
        </Button>
        {me.avatar_url && (
          <Button variant="ghost" disabled={photoBusy} onClick={removePhoto}>
            Remove photo
          </Button>
        )}
        <span className={styles.muted}>Shown beside your requests and in the play history.</span>
        <FormError message={photoError} />
      </div>
      <PhotoCropper
        file={cropping}
        busy={photoBusy}
        error={cropError}
        onCancel={() => setCropping(null)}
        onCrop={savePhoto}
      />

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

          <InstallApp />
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
      <ButtonLink to="/queue" variant="secondary">
        Request a song
      </ButtonLink>
    </div>
  );
}
