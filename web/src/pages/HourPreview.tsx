import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { api, errorText, type Hour, type HourSlot, type Jingle, type StationFields } from "../api";
import { Button } from "../components/Button";
import { Dialog } from "../components/Dialog";
import { Icon } from "../components/Icon";
import { PreviewButton } from "../components/PreviewButton";
import { FormError } from "../components/TextField";
import { clock } from "../live/usePlayback";
import h from "./HourPreview.module.css";
import styles from "./Page.module.css";

type Voice = { voice: string; dj_name: string; personality: string };

function time(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

type Props = {
  open: boolean;
  onClose: () => void;
  /** The station as the editor had it when the preview was opened. */
  station: StationFields;
  /** A saved station's id, so its recent picks are left out as they would be for real. */
  stationId: number | null;
};

/** An hour of a station worked out in advance: its songs, and what the DJ says and where. */
export function HourPreview({ open, onClose, station, stationId }: Props) {
  const [hour, setHour] = useState<Hour | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Bumped by every run, and on closing, so a slow answer that's no longer wanted is ignored.
  const latest = useRef(0);

  const run = useCallback(async () => {
    const mine = ++latest.current;
    setLoading(true);
    setError(null);
    setHour(null);
    try {
      const found = await api<Hour>("POST", "/stations/preview-hour", {
        ...station,
        station_id: stationId,
      });
      if (mine === latest.current) setHour(found);
    } catch (caught) {
      if (mine === latest.current) setError(errorText(caught));
    } finally {
      if (mine === latest.current) setLoading(false);
    }
  }, [station, stationId]);

  // A fresh hour each time it's opened.
  const runLatest = useRef(run);
  runLatest.current = run;
  useEffect(() => {
    if (open) runLatest.current();
    else latest.current++;
  }, [open]);

  const voice = { voice: station.voice, dj_name: station.dj_name, personality: station.personality };
  const talks = hour?.slots.filter((slot) => slot.line).length ?? 0;
  const jingles = hour?.slots.filter((slot) => slot.jingle).length ?? 0;

  return (
    <Dialog open={open} onClose={onClose} title={`An hour of ${station.name || "this station"}`} tall>
      <div className={h.body}>
        {loading && (
          <p role="status" className={h.waiting}>
            <Icon name="radio" size={18} />
            Picking an hour of songs{station.dj ? " and writing what the DJ says" : ""}. This
            takes about a minute.
          </p>
        )}
        <FormError message={error} />
        {hour && (
          <>
            <p className={styles.muted}>
              {hour.slots.length} songs, {hour.minutes} minutes
              {jingles ? `, ${jingles} ${jingles === 1 ? "jingle" : "jingles"}` : ""}
              {station.dj ? `, and ${station.dj_name} talks ${talks} times` : ""}. Requests would
              play first, so the real hour will differ. Nothing here is kept.
            </p>
            {(station.dj || jingles > 0) && (
              <ul className={h.legend} aria-label="Key">
                <li>
                  <span className={h.keySong} aria-hidden="true" />
                  A song
                </li>
                {jingles > 0 && (
                  <li>
                    <span className={h.keyJingle} aria-hidden="true" />
                    A jingle between songs: the music pauses
                  </li>
                )}
                {station.dj && (
                  <>
                    <li>
                      <span className={h.keyBetween} aria-hidden="true" />
                      The DJ between songs: the music pauses
                    </li>
                    <li>
                      <span className={h.keyOver} aria-hidden="true" />
                      The DJ over the start of a song: the music dips
                    </li>
                  </>
                )}
              </ul>
            )}
            <ol className={h.run}>
              {hour.slots.map((slot) => (
                <Fragment key={slot.track.id}>
                  {slot.jingle && (
                    <li className={h.betweenRow}>
                      <JingleLine jingle={slot.jingle} />
                    </li>
                  )}
                  {slot.line?.where === "between" && (
                    <li className={h.betweenRow}>
                      <DJLine script={slot.line.script} label="Between songs" voice={voice} />
                    </li>
                  )}
                  <SongRow slot={slot} voice={voice} />
                </Fragment>
              ))}
            </ol>
            <Button variant="secondary" className={h.again} onClick={run} disabled={loading}>
              Try another hour
            </Button>
          </>
        )}
      </div>
    </Dialog>
  );
}

function SongRow({ slot, voice }: { slot: HourSlot; voice: Voice }) {
  const { track } = slot;
  return (
    <li className={h.song}>
      <span className={h.time}>{time(slot.starts_at)}</span>
      <div className={h.songCard}>
        <div className={h.songTop}>
          {track.art_url ? (
            <img src={track.art_url} alt="" loading="lazy" className={h.art} />
          ) : (
            <span aria-hidden="true" className={h.art} />
          )}
          <span className={h.songText}>
            <span className={h.title}>{track.title}</span>
            <span className={h.meta}>
              {track.artists} · {clock(track.duration)}
            </span>
            {slot.note && <span className={h.note}>{slot.note}</span>}
          </span>
        </div>
        {slot.line?.where === "over_intro" && (
          <DJLine script={slot.line.script} label="Over the start of this song" voice={voice} over />
        )}
      </div>
    </li>
  );
}

type LineProps = { script: string; label: string; voice: Voice; over?: boolean };

function DJLine({ script, label, voice, over = false }: LineProps) {
  const [error, setError] = useState<string | null>(null);
  return (
    <div className={`${h.line} ${over ? h.over : h.between}`}>
      <span className={h.lineLabel}>
        <Icon name="announce" size={15} />
        {label}
      </span>
      <p className={h.script}>“{script}”</p>
      <div className={h.lineFoot}>
        <FormError message={error} />
        <PreviewButton text={script} endpoint="/stations/preview" extra={voice} onError={setError} />
      </div>
    </div>
  );
}

/** A jingle in the hour, to listen to here. */
function JingleLine({ jingle }: { jingle: Jingle }) {
  const [playing, setPlaying] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);

  const stop = useCallback(() => {
    audio.current?.pause();
    audio.current = null;
    setPlaying(false);
  }, []);
  useEffect(() => stop, [stop]);

  const press = () => {
    if (playing) {
      stop();
      return;
    }
    audio.current = new Audio(jingle.url);
    audio.current.onended = stop;
    setPlaying(true);
    audio.current.play().catch(stop);
  };

  return (
    <div className={`${h.line} ${h.jingle}`}>
      <span className={h.lineLabel}>
        <Icon name="jingle" size={15} />
        {jingle.kind === "station" ? "Station ident" : "System ident"}
      </span>
      <div className={h.jingleTop}>
        <span className={h.jingleName}>
          {jingle.name} <span className={h.meta}>· {clock(jingle.seconds)}</span>
        </span>
        <Button variant="secondary" onClick={press}>
          <Icon name={playing ? "stop" : "play"} size={14} />
          {playing ? "Stop" : "Listen"}
        </Button>
      </div>
    </div>
  );
}
