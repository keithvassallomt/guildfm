import { type ReactNode, useState } from "react";
import { Link } from "react-router";
import type { NowState, PlaylistTile, QueueEntry, QueueState, SourceKind } from "../api";
import { Icon } from "../components/Icon";
import { SegmentedControl } from "../components/SegmentedControl";
import { ago } from "../live/status";
import n from "./NowPlaying.module.css";

/** What the sources need from the page: what's on, and how to switch. */
export type Sources = {
  now: NowState | null;
  queue: QueueState | null;
  /** The music is playing, so a switch waits for the current song. */
  playing: boolean;
  canSwitch: boolean;
  pick: (playlist: PlaylistTile) => void;
  requestsOnly: () => void;
};

const NAMES: Record<SourceKind, string> = { queue: "Queue", library: "Library", radio: "Radio" };

/** Three bouncing bars: this is what's on air. */
export function OnAirBars({ dark = false }: { dark?: boolean }) {
  return (
    <span aria-hidden="true" className={`${n.bars} ${dark ? n.dark : ""}`}>
      <span />
      <span />
      <span />
    </span>
  );
}

function Needle() {
  return <span aria-hidden="true" className={n.needle} />;
}

function Cover({ url }: { url: string | null }) {
  return url ? (
    <img src={url} alt="" className={n.cover} />
  ) : (
    <span aria-hidden="true" className={n.cover} />
  );
}

/** A playlist's art: four covers from its songs, or one, or a placeholder. */
function Covers({ urls }: { urls: string[] }) {
  if (urls.length >= 4) {
    return (
      <span aria-hidden="true" className={n.mosaic}>
        {urls.slice(0, 4).map((url) => (
          <img key={url} src={url} alt="" />
        ))}
      </span>
    );
  }
  if (urls.length > 0) return <img src={urls[0]} alt="" className={n.cover} />;
  return (
    <span aria-hidden="true" className={n.cover}>
      <Icon name="library" size={26} />
    </span>
  );
}

function score(value: number): string {
  return `${value > 0 ? "+" : ""}${value}`;
}

function lastPlayed(playlist: PlaylistTile): string {
  if (playlist.on_air) return "Playing now";
  return playlist.last_played_at ? `Played ${ago(playlist.last_played_at)}` : "Not played yet";
}

/** The queue's side: the request playing, the one locked in next, then the vote. */
function queueParts(sources: Sources) {
  const { now, queue } = sources;
  const playing = now?.on_air === "queue" && queue?.playing?.requested_by ? queue.playing : null;
  const next = queue?.next?.requested_by ? queue.next : null;
  const waiting = queue?.waiting ?? [];
  return { playing, next, waiting, count: waiting.length + (next ? 1 : 0) };
}

/** What the playlist filling the gaps is waiting for, when it isn't on air itself. */
function fillerLabel(sources: Sources): string {
  const { next, waiting } = queueParts(sources);
  if (next || waiting.length > 0) return "Fills the gaps";
  return sources.playing ? "After this song" : "Up next";
}

function PlaylistBadge({ playlist, sources }: { playlist: PlaylistTile; sources: Sources }) {
  if (playlist.on_air) {
    return (
      <span className={n.onAirText}>
        <OnAirBars />
        On air
      </span>
    );
  }
  return playlist.filling ? <span className={n.fillBadge}>{fillerLabel(sources)}</span> : null;
}

function OnAirPill() {
  return (
    <span className={n.pill}>
      <OnAirBars dark />
      On air
    </span>
  );
}

/** A button when the viewer can switch to it, otherwise just the content. */
function Pickable({
  className,
  onPick,
  children,
}: {
  className: string;
  onPick?: () => void;
  children: ReactNode;
}) {
  return onPick ? (
    <button type="button" className={`${className} ${n.pickable}`} onClick={onPick}>
      {children}
    </button>
  ) : (
    <div className={className}>{children}</div>
  );
}

// Desktop: bands of tiles, a needle on what's on air

type BandProps = {
  id: string;
  label: string;
  note: string;
  onAir: boolean;
  link?: ReactNode;
  children: ReactNode;
};

function Band({ id, label, note, onAir, link, children }: BandProps) {
  return (
    <section className={n.band} aria-labelledby={id}>
      <div className={n.bandTop}>
        <h2 id={id} className={`${n.bandLabel} ${onAir ? n.bandOn : ""}`}>
          {label}
        </h2>
        <span className={n.bandNote}>{note}</span>
        {onAir && <OnAirPill />}
        {link}
      </div>
      <div className={n.strip}>{children}</div>
    </section>
  );
}

function RequestTile({ entry, caption, onAir }: { entry: QueueEntry; caption: ReactNode; onAir?: boolean }) {
  return (
    <div className={`${n.tile} ${onAir ? `${n.on} ${n.glow}` : ""}`}>
      <Cover url={entry.track.art_url} />
      <span className={n.tileText}>
        <span className={n.tileName}>{entry.track.title}</span>
        <span className={n.tileCaption}>{entry.track.artists}</span>
      </span>
      <span className={n.tileFoot}>{caption}</span>
      {onAir && <Needle />}
    </div>
  );
}

export function Bands(sources: Sources) {
  const { now, canSwitch, pick, requestsOnly } = sources;
  const { playing, next, waiting, count } = queueParts(sources);
  const playlists = now?.playlists ?? [];

  return (
    <div className={n.bands}>
      <p className={n.hint}>
        Requests always play first.{" "}
        {canSwitch
          ? "Pick a playlist to fill the gaps between them: it takes over after this song."
          : "Curators and admins choose what fills the gaps between them."}
      </p>

      <Band
        id="band-queue"
        label="Queue"
        note={`${count} waiting · by votes`}
        onAir={now?.on_air === "queue"}
        link={
          <Link to="/queue" className={n.bandLink}>
            Open the queue
            <Icon name="chevronRight" size={14} />
          </Link>
        }
      >
        {playing && (
          <RequestTile
            entry={playing}
            onAir
            caption={<span className={n.tileCaption}>Playing · {playing.requested_by?.display_name}</span>}
          />
        )}
        {next && (
          <RequestTile
            entry={next}
            caption={<span className={n.tileCaption}>Up next · {next.requested_by?.display_name}</span>}
          />
        )}
        {waiting.map((entry, index) => (
          <RequestTile
            key={entry.id}
            entry={entry}
            caption={
              <>
                <span className={n.tileCaption}>
                  #{index + 1} · {entry.requested_by?.display_name}
                </span>
                <span className={n.score}>{score(entry.score)}</span>
              </>
            }
          />
        ))}
        {count === 0 && !playing && (
          <p className={n.emptyTile}>No requests waiting. A request always plays first.</p>
        )}
        {canSwitch && (
          <button
            type="button"
            aria-pressed={now?.requests_only ?? false}
            className={`${n.tile} ${n.onlyTile}`}
            onClick={requestsOnly}
          >
            <Icon name="queue" size={22} />
            <span className={n.tileName}>Requests only</span>
            <span className={n.onlyNote}>Nothing fills the gaps</span>
          </button>
        )}
      </Band>

      <Band
        id="band-library"
        label="Library"
        note="Playlists · last played first"
        onAir={now?.on_air === "library"}
        link={
          canSwitch && (
            <Link to="/library" className={n.bandLink}>
              All playlists
              <Icon name="chevronRight" size={14} />
            </Link>
          )
        }
      >
        {playlists.map((playlist) => (
          <Pickable
            key={playlist.id}
            className={`${n.tile} ${playlist.on_air ? `${n.on} ${n.glow}` : ""}`}
            onPick={canSwitch ? () => pick(playlist) : undefined}
          >
            <Covers urls={playlist.covers} />
            <span className={n.tileText}>
              <span className={n.tileName}>{playlist.name}</span>
              <span className={n.tileCaption}>{lastPlayed(playlist)}</span>
            </span>
            <span className={n.tileFoot}>
              <PlaylistBadge playlist={playlist} sources={sources} />
            </span>
            {playlist.on_air && <Needle />}
          </Pickable>
        ))}
        {now && playlists.length === 0 && <p className={n.emptyTile}>No playlists yet.</p>}
      </Band>

      <Band id="band-radio" label="Radio" note="AI stations · last played first" onAir={false}>
        <p className={n.emptyTile}>AI stations, each with its own DJ, arrive in stage 10.</p>
      </Band>
    </div>
  );
}

// Phone: the three sources as tabs

function RequestRow({ entry, caption, onAir }: { entry: QueueEntry; caption: ReactNode; onAir?: boolean }) {
  return (
    <li className={`${n.row} ${onAir ? `${n.on} ${n.glow}` : ""}`}>
      <Cover url={entry.track.art_url} />
      <span className={n.rowText}>
        <span className={n.rowName}>{entry.track.title}</span>
        <span className={n.rowCaption}>
          {entry.track.artists} · {caption}
        </span>
      </span>
      {onAir && <OnAirBars />}
      {!onAir && entry.state === "waiting" && <span className={n.score}>{score(entry.score)}</span>}
    </li>
  );
}

export function SourceTabs(sources: Sources) {
  const { now, canSwitch, pick, requestsOnly } = sources;
  const { playing, next, waiting, count } = queueParts(sources);
  const onAir = now?.on_air ?? null;
  // Until someone picks a tab, show whichever source is on air.
  const [chosen, setChosen] = useState<SourceKind | null>(null);
  const tab = chosen ?? onAir ?? (now?.requests_only === false ? "library" : "queue");
  const playlists = now?.playlists ?? [];

  return (
    <section className={n.sources} aria-labelledby="sources">
      <div className={n.sourcesTop}>
        <h2 id="sources" className={n.sourcesTitle}>
          Sources
        </h2>
        <p className={n.hint}>
          Requests always play first.{" "}
          {canSwitch
            ? "Pick a playlist to fill the gaps after this song."
            : "Curators and admins choose what fills the gaps."}
        </p>
      </div>
      <SegmentedControl
        label="Sources"
        value={tab}
        onChange={setChosen}
        options={(["queue", "library", "radio"] as const).map((kind) => ({
          value: kind,
          label: (
            <span className={n.tabLabel}>
              {onAir === kind && <OnAirBars />}
              {NAMES[kind]}
            </span>
          ),
        }))}
      />

      {tab === "queue" && (
        <>
          <span className={n.bandNote}>{count} waiting · by votes</span>
          <ol className={n.list}>
            {playing && (
              <RequestRow
                entry={playing}
                onAir
                caption={`Playing · ${playing.requested_by?.display_name}`}
              />
            )}
            {next && <RequestRow entry={next} caption={`Up next · ${next.requested_by?.display_name}`} />}
            {waiting.map((entry) => (
              <RequestRow key={entry.id} entry={entry} caption={entry.requested_by?.display_name} />
            ))}
          </ol>
          {count === 0 && !playing && (
            <p className={n.emptyRow}>No requests waiting. A request always plays first.</p>
          )}
          <div className={n.listFoot}>
            {canSwitch && (
              <button
                type="button"
                aria-pressed={now?.requests_only ?? false}
                className={n.only}
                onClick={requestsOnly}
              >
                Requests only
              </button>
            )}
            <Link to="/queue" className={n.queueLink}>
              Open the queue
              <Icon name="chevronRight" size={16} />
            </Link>
          </div>
        </>
      )}

      {tab === "library" && (
        <>
          <span className={n.bandNote}>Playlists · last played first</span>
          <ul className={n.list}>
            {playlists.map((playlist) => (
              <li key={playlist.id}>
                <Pickable
                  className={`${n.row} ${playlist.on_air ? `${n.on} ${n.glow}` : ""}`}
                  onPick={canSwitch ? () => pick(playlist) : undefined}
                >
                  <Covers urls={playlist.covers} />
                  <span className={n.rowText}>
                    <span className={n.rowName}>{playlist.name}</span>
                    <span className={n.rowCaption}>{lastPlayed(playlist)}</span>
                  </span>
                  <PlaylistBadge playlist={playlist} sources={sources} />
                </Pickable>
              </li>
            ))}
          </ul>
          {now && playlists.length === 0 && <p className={n.emptyRow}>No playlists yet.</p>}
        </>
      )}

      {tab === "radio" && (
        <p className={n.emptyRow}>AI stations, each with its own DJ, arrive in stage 10.</p>
      )}
    </section>
  );
}
