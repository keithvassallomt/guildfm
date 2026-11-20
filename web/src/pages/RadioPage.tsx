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
import { kindOf, kindTitle, mixText, oftenText, saysText } from "../station/kinds";
import { listed } from "./announcementText";
import lib from "./Library.module.css";
import styles from "./Page.module.css";
import { usePlaylistPlayer } from "./PlaylistsPage";

/** What a station is like, as short tags: "Music with a DJ", "DJ Della", "Every few songs"... */
export function stationTags(station: Station): string[] {
  if (station.kind === "ai_picks") return ["Built in", "Follows what's been playing"];
  const kind = kindOf(station);
  const tags = [kindTitle(kind)];
  if (kind === "talk") {
    tags.push(`Hosts ${listed(station.djs.map((dj) => dj.name))}`);
    tags.push(mixText(station.talk_ratio));
  } else if (kind === "dj") {
    tags.push(`DJ ${station.dj_name}`, oftenText(station.talk_every, station.talk_unit));
    tags.push(saysText(station.style));
  }
  if (kind !== "music" && station.announce_requests) tags.push("Says who asked");
  if (station.global_awareness) tags.push("Knows what's going on");
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
            <li
              key={station.id}
              className={`${lib.station} ${canMake && station.kind === "custom" ? lib.opens : ""}`}
            >
              <div className={lib.stationTop}>
                <StationCover url={station.art_url} className={lib.stationArt} iconSize={26} />
                <span className={lib.text}>
                  {canMake && station.kind === "custom" ? (
                    // Its ::after covers the card, so the whole card opens the station's page.
                    <Link to={`/radio/${station.id}`} className={`${lib.stationName} ${lib.cardLink}`}>
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
            New station
          </ButtonLink>
        </div>
      )}
      {toast}
      {offToast}
    </div>
  );
}
