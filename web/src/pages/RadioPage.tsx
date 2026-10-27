import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { api, errorText, type Station } from "../api";
import { useAuth } from "../auth/AuthProvider";
import { Button, ButtonLink } from "../components/Button";
import { HelpLink } from "../components/HelpLink";
import { Icon } from "../components/Icon";
import { StationCover } from "../components/StationCover";
import { FormError } from "../components/TextField";
import { useToast } from "../components/Toast";
import { useLiveEvent } from "../live/LiveProvider";
import lib from "./Library.module.css";
import styles from "./Page.module.css";
import { usePlaylistPlayer } from "./PlaylistsPage";

/** What a station is like, as short tags: "DJ Della", "Talks every 3 tracks"... */
export function stationTags(station: Station): string[] {
  if (station.kind === "ai_picks") return ["Built in", "Follows what's been playing"];
  const tags: string[] = [];
  if (station.dj) {
    const unit = station.talk_unit === "tracks" ? "track" : "minute";
    const every = station.talk_every === 1 ? unit : `${station.talk_every} ${unit}s`;
    tags.push(`DJ ${station.dj_name}`, `Talks every ${every}`);
    tags.push(station.style === "commentary" ? "Commentary" : "Just the songs");
    if (station.announce_requests) tags.push("Announces requests");
  } else {
    tags.push("No DJ");
  }
  if (station.global_awareness) tags.push("Global awareness");
  return tags;
}

/** The AI stations: what each is like, switching to one, and making new ones. */
export function RadioPage() {
  const { can } = useAuth();
  const canMake = can("create_stations");
  const [stations, setStations] = useState<Station[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { show, toast } = useToast();
  const location = useLocation();
  const navigate = useNavigate();

  const load = useCallback(() => {
    api<Station[]>("GET", "/stations")
      .then(setStations)
      .catch((caught) => setError(errorText(caught)));
  }, []);
  useEffect(load, [load]);
  useLiveEvent("queue", load);
  const { takeOff, toast: offToast } = usePlaylistPlayer(load);

  // The station editor sends people back here with a word about what it did.
  const said = (location.state as { said?: string } | null)?.said;
  useEffect(() => {
    if (!said) return;
    show(said);
    navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
  }, [said, show, navigate, location.pathname, location.search]);

  const putOn = async (station: Station) => {
    try {
      await api("POST", `/stations/${station.id}/play`);
      show(`${station.name} takes over from the next song. Requests still play first.`);
    } catch (caught) {
      show(errorText(caught));
    }
    load();
  };

  const playing = stations?.find((station) => station.playing);

  return (
    <div className={`${styles.page} ${styles.narrow}`}>
      <header className={styles.header}>
        <h1 className={styles.title}>Radio</h1>
        <HelpLink />
      </header>

      {playing && (
        <div className={lib.playing} role="status">
          <Icon name="radio" size={18} />
          <span className={lib.playingText}>
            Playing from <strong>{playing.name}</strong>. Requests always play first.
          </span>
          <Button variant="secondary" onClick={takeOff}>
            Take off
          </Button>
        </div>
      )}

      <FormError message={error} />
      {stations && (
        <ul className={lib.stations}>
          {stations.map((station) => (
            <li key={station.id} className={lib.station}>
              <div className={lib.stationTop}>
                <StationCover url={station.art_url} className={lib.stationArt} iconSize={26} />
                <span className={lib.text}>
                  {canMake && station.kind === "custom" ? (
                    <Link to={`/radio/${station.id}`} className={lib.stationName}>
                      {station.name}
                    </Link>
                  ) : (
                    <span className={lib.stationName}>{station.name}</span>
                  )}
                  <span className={lib.stationBrief}>{station.description}</span>
                </span>
                {station.playing && <span className={lib.onAir}>On air</span>}
              </div>
              <div className={lib.tags}>
                {stationTags(station).map((tag) => (
                  <span key={tag} className={lib.tag}>
                    {tag}
                  </span>
                ))}
              </div>
              {!station.playing && (
                <Button
                  variant="secondary"
                  className={lib.switch}
                  onClick={() => putOn(station)}
                >
                  <Icon name="play" size={14} />
                  Switch to this station
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}

      {canMake && (
        <div className={lib.actions}>
          <ButtonLink to="/radio/new">
            <Icon name="plus" size={16} strokeWidth={2.6} />
            New AI station
          </ButtonLink>
        </div>
      )}
      {toast}
      {offToast}
    </div>
  );
}
