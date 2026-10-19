import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { api, errorText, type Lineup, type LineupDay } from "../api";
import { useAuth } from "../auth/AuthProvider";
import { Button, ButtonLink } from "../components/Button";
import { Icon } from "../components/Icon";
import { LineupCover } from "../components/LineupCover";
import { FormError } from "../components/TextField";
import { useToast } from "../components/Toast";
import { clock, stretches } from "../lineups/time";
import { useLiveEvent } from "../live/LiveProvider";
import { useNow } from "../live/useNow";
import l from "./Lineups.module.css";
import styles from "./Page.module.css";

/** The day as a thin bar: shows, playlists and the gaps between them. */
export function DayBar({ lineup, day }: { lineup: Lineup; day: LineupDay }) {
  const span = day.end - day.start;
  const label = lineup.slots.map((slot) => `${clock(slot.start)} ${slot.name}`).join(", ");
  const hours = [];
  for (let hour = Math.ceil(day.start / 60) * 60; hour <= day.end; hour += 120) hours.push(hour);
  return (
    <div className={l.dayBar}>
      <div role="img" aria-label={label || "Nothing planned yet"} className={l.barTrack}>
        {stretches(lineup.slots, day).map((stretch) => (
          <span
            key={stretch.start}
            className={`${l.segment} ${stretch.slot ? l[stretch.slot.kind] : l.gap}`}
            style={{
              left: `calc(${((stretch.start - day.start) / span) * 100}% + 1px)`,
              width: `calc(${((stretch.end - stretch.start) / span) * 100}% - 2px)`,
            }}
          />
        ))}
      </div>
      <div className={l.barHours}>
        {hours.map((hour) => (
          <span key={hour}>{clock(hour)}</span>
        ))}
      </div>
    </div>
  );
}

/** Shows, playlists and gaps, as the bars colour them. */
export function Legend({ day }: { day?: LineupDay }) {
  return (
    <div className={l.legend}>
      <span className={l.key}>
        <span className={`${l.swatch} ${l.show}`} />
        Shows
      </span>
      <span className={l.key}>
        <span className={`${l.swatch} ${l.playlist}`} />
        Playlists
      </span>
      <span className={l.key}>
        <span className={`${l.swatch} ${l.gap}`} />
        Gaps: when the queue runs out
      </span>
      {day && (
        <span className={l.dayNote}>
          Day: {clock(day.start)} to {clock(day.end)}, from the playback hours
        </span>
      )}
    </div>
  );
}

/** The line-ups: what each plans, putting one on, and making new ones. */
export function LineupsPage() {
  const { can } = useAuth();
  const canPlan = can("plan_lineups");
  const { now } = useNow();
  const [lineups, setLineups] = useState<Lineup[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { show, toast } = useToast();
  const location = useLocation();
  const navigate = useNavigate();

  const load = useCallback(() => {
    api<Lineup[]>("GET", "/lineups")
      .then(setLineups)
      .catch((caught) => setError(errorText(caught)));
  }, []);
  useEffect(load, [load]);
  useLiveEvent("queue", load);

  // The editor sends people back here with a word about what it did.
  const said = (location.state as { said?: string } | null)?.said;
  useEffect(() => {
    if (!said) return;
    show(said);
    navigate(location.pathname, { replace: true, state: null });
  }, [said, show, navigate, location.pathname]);

  const putOn = async (lineup: Lineup) => {
    try {
      await api("POST", `/lineups/${lineup.id}/play`);
      show(`${lineup.name} takes over from the next song. Requests still play first.`);
    } catch (caught) {
      show(errorText(caught));
    }
    load();
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerStart}>
          <Link to="/" aria-label="Back to Now Playing" className={`${styles.iconLink} ${l.back}`}>
            <Icon name="back" />
          </Link>
          <h1 className={styles.title}>Line-ups</h1>
        </div>
        {canPlan && (
          <ButtonLink to="/lineups/new">
            <Icon name="plus" size={16} strokeWidth={2.6} />
            New line-up
          </ButtonLink>
        )}
      </header>
      <p className={`${styles.muted} ${l.intro}`}>
        Plan the day: which shows and playlists fill the gaps between requests, by the clock. Put
        one on here or on Now Playing, and it stays on, day after day, until someone picks
        something else.
      </p>
      <Legend day={now?.day} />

      <FormError message={error} />
      {lineups && now && (
        <ul className={l.grid}>
          {lineups.map((lineup) => {
            const shows = lineup.slots.filter((slot) => slot.kind === "show").length;
            const lists = lineup.slots.length - shows;
            return (
              <li key={lineup.id} className={`${l.card} ${lineup.on ? l.cardOn : ""}`}>
                <div className={l.cardTop}>
                  <LineupCover url={lineup.art_url} className={l.cover} iconSize={30} />
                  <div className={l.cardText}>
                    <span className={l.nameRow}>
                      <h2 className={l.name}>{lineup.name}</h2>
                      {lineup.on && <span className={l.onAir}>On air</span>}
                    </span>
                    {lineup.description && <p className={l.description}>{lineup.description}</p>}
                    <span className={l.summary}>
                      {shows} {shows === 1 ? "show" : "shows"}, {lists}{" "}
                      {lists === 1 ? "playlist" : "playlists"}
                      {lineup.made_by ? ` · by ${lineup.made_by}` : ""}
                    </span>
                  </div>
                </div>
                <DayBar lineup={lineup} day={now.day} />
                <div className={l.buttons}>
                  {canPlan && (
                    <ButtonLink variant="secondary" to={`/lineups/${lineup.id}`}>
                      Edit
                    </ButtonLink>
                  )}
                  {!lineup.on && (
                    <Button variant="secondary" onClick={() => putOn(lineup)}>
                      <Icon name="play" size={14} />
                      Put on
                    </Button>
                  )}
                </div>
              </li>
            );
          })}
          {canPlan && (
            <li>
              <Link to="/lineups/new" className={l.newCard}>
                <Icon name="plus" size={26} />
                New line-up
              </Link>
            </li>
          )}
        </ul>
      )}
      {lineups?.length === 0 && !canPlan && (
        <p className={styles.muted}>No line-ups yet. Curators and admins make them.</p>
      )}
      {toast}
    </div>
  );
}
