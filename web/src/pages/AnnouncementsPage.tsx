import { useCallback, useEffect, useId, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import {
  type Announcement,
  type AnnouncementLog,
  type AnnouncementsState,
  api,
  errorText,
} from "../api";
import { ButtonLink, Button } from "../components/Button";
import { Icon } from "../components/Icon";
import { FormError } from "../components/TextField";
import { useToast } from "../components/Toast";
import { Toggle } from "../components/Toggle";
import { useLiveEvent } from "../live/LiveProvider";
import a from "./Announcements.module.css";
import {
  HOW,
  describeNext,
  describePlayed,
  describeWhen,
  describeWhere,
} from "./announcementText";
import styles from "./Page.module.css";

/** Scheduled announcements, with their on/off switches, and what played lately. */
export function AnnouncementsPage() {
  const [data, setData] = useState<AnnouncementsState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { show, toast } = useToast();
  const location = useLocation();
  const navigate = useNavigate();

  const load = useCallback(() => {
    api<AnnouncementsState>("GET", "/announcements")
      .then(setData)
      .catch((caught) => setError(errorText(caught)));
  }, []);
  useEffect(load, [load]);
  useLiveEvent("announcements", load);

  // The editor sends people back here with a word about what it did.
  const said = (location.state as { said?: string } | null)?.said;
  useEffect(() => {
    if (!said) return;
    show(said);
    navigate(location.pathname, { replace: true, state: null });
  }, [said, show, navigate, location.pathname]);

  const toggle = async (item: Announcement, active: boolean) => {
    setData(
      (current) =>
        current && {
          ...current,
          scheduled: current.scheduled.map((s) => (s.id === item.id ? { ...s, active } : s)),
        },
    );
    try {
      await api("PATCH", `/announcements/${item.id}`, { active });
    } catch (caught) {
      show(errorText(caught));
    }
    load();
  };

  const playNow = async (item: Announcement) => {
    try {
      await api("POST", `/announcements/${item.id}/play`);
      const where = item.rooms ? item.rooms.map((room) => room.name).join(", ") : "all rooms";
      show(`Playing now in ${where}, over the music.`);
    } catch (caught) {
      show(errorText(caught));
    }
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerStart}>
          <Link to="/admin" aria-label="Back to Admin" className={styles.iconLink}>
            <Icon name="back" />
          </Link>
          <h1 className={styles.title}>Announcements</h1>
        </div>
        <ButtonLink to="/admin/announcements/new">
          <Icon name="plus" size={16} strokeWidth={2.6} />
          New
        </ButtonLink>
      </header>

      <p className={styles.muted}>
        Announcements always go before the DJ. They don't play while GuildFM is stopped or
        outside playback hours.
      </p>
      <FormError message={error} />

      {data && (
        <div className={styles.columns}>
          <section className={styles.section} aria-labelledby="scheduled">
            <h2 id="scheduled" className={styles.sectionTitle}>
              Scheduled
            </h2>
            {data.scheduled.length === 0 ? (
              <div className={styles.empty}>
                <p className={styles.emptyText}>
                  Nothing scheduled. Make one for lunchtime, Friday drinks or a fire alarm test.
                </p>
                <ButtonLink variant="secondary" to="/admin/announcements/new">
                  New announcement
                </ButtonLink>
              </div>
            ) : (
              <ul className={a.cards}>
                {data.scheduled.map((item) => (
                  <ScheduledCard
                    key={item.id}
                    item={item}
                    onToggle={(active) => toggle(item, active)}
                    onPlay={() => playNow(item)}
                  />
                ))}
              </ul>
            )}
          </section>

          <section className={styles.section} aria-labelledby="recent">
            <h2 id="recent" className={styles.sectionTitle}>
              Recently played
            </h2>
            {data.recent.length === 0 ? (
              <p className={styles.muted}>Nothing has been announced yet.</p>
            ) : (
              <ul className={a.log}>
                {data.recent.map((entry) => (
                  <LogEntry key={entry.id} entry={entry} />
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
      {toast}
    </div>
  );
}

type CardProps = { item: Announcement; onToggle: (active: boolean) => void; onPlay: () => void };

function ScheduledCard({ item, onToggle, onPlay }: CardProps) {
  const labelId = useId();
  const rooms = item.rooms?.map((room) => room.name) ?? null;

  return (
    <li className={a.card} data-off={!item.active}>
      <p className={a.text}>“{item.text}”</p>
      <div className={a.chips}>
        <span className={a.chip}>
          <Icon name="clock" size={12} strokeWidth={2.4} />
          {describeWhen(item)}
        </span>
        <span className={a.chip}>{describeWhere(rooms)}</span>
        <span className={a.chip}>{HOW[item.mode]}</span>
        {item.next_at && !item.in_hours && (
          <span className={`${a.chip} ${a.warnChip}`}>Outside playback hours</span>
        )}
      </div>
      {item.active && <span className={a.next}>{describeNext(item)}</span>}
      <div className={a.cardActions}>
        <Button variant="secondary" onClick={onPlay}>
          <Icon name="play" size={14} />
          Play now
        </Button>
        <Link to={`/admin/announcements/${item.id}`} className={a.edit}>
          Edit
        </Link>
        <span className={a.switch}>
          <span id={labelId} className={a.switchLabel}>
            {item.active ? "Active" : "Paused"}
          </span>
          <Toggle checked={item.active} onChange={onToggle} labelledBy={labelId} />
        </span>
      </div>
    </li>
  );
}

function LogEntry({ entry }: { entry: AnnouncementLog }) {
  return (
    <li className={a.logEntry}>
      <span className={a.logText}>“{entry.text}”</span>
      <span className={a.logMeta}>
        {describePlayed(entry.played_at)} · {describeWhere(entry.rooms)}
      </span>
      {entry.problem && <span className={a.problem}>Didn't play: {entry.problem}</span>}
    </li>
  );
}
