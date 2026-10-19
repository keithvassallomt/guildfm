import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import type { LineupSlot, LineupTile, NowState } from "../api";
import { Icon } from "../components/Icon";
import { LineupCover } from "../components/LineupCover";
import { clock, type Stretch, stretches, summary } from "../lineups/time";
import { ago } from "../live/status";
import n from "./NowPlaying.module.css";

const PX = 3.4; // the desktop strip's pixels a minute
const TICK_MS = 15_000;

/** The time in the office in minutes, ticking on from when Now Playing last heard from the
 * server, with the seconds as a fraction so the needle moves smoothly. */
function useOfficeMinute(now: NowState | null): number | null {
  const fetched = useRef({ minute: 0, at: 0 });
  const [, tick] = useState(0);
  if (now && now.minute !== fetched.current.minute) {
    fetched.current = { minute: now.minute, at: Date.now() };
  }
  useEffect(() => {
    const timer = window.setInterval(() => tick((count) => count + 1), TICK_MS);
    return () => window.clearInterval(timer);
  }, []);
  if (!now) return null;
  return fetched.current.minute + (Date.now() - fetched.current.at) / 60_000;
}

/** The line-up that's on, if any. */
export function lineupOn(now: NowState | null): LineupTile | null {
  return now?.lineups.find((lineup) => lineup.on) ?? null;
}

function slotMeta(slot: LineupSlot | null): string {
  if (!slot) return "A gap: when the queue runs out";
  if (slot.kind === "show") return slot.dj_name ? `Show · DJ ${slot.dj_name}` : "Show · no DJ";
  const runs = slot.end - slot.start;
  return slot.minutes && runs < slot.minutes ? `Playlist · cut at ${clock(slot.end)}` : "Playlist";
}

function lastOn(lineup: LineupTile): string {
  if (lineup.on) return "On air";
  return lineup.last_on_at ? `On ${ago(lineup.last_on_at)}` : "Not on yet";
}

/** The rest of the day from the slot on now, or the whole day outside playback hours. */
function upcoming(lineup: LineupTile, now: NowState, minute: number) {
  const day = stretches(lineup.slots, now.day);
  const index = day.findIndex((stretch) => minute >= stretch.start && minute < stretch.end);
  return { onNow: index >= 0, rest: index >= 0 ? day.slice(index) : day };
}

function SlotArt({ stretch }: { stretch: Stretch }) {
  const slot = stretch.slot;
  if (slot?.art_url) return <img src={slot.art_url} alt="" className={n.slotArt} />;
  const icon = !slot ? "lineups" : slot.kind === "show" ? "radio" : "library";
  return (
    <span aria-hidden="true" className={n.slotArt}>
      <Icon name={icon} size={18} />
    </span>
  );
}

type Props = {
  now: NowState | null;
  canSwitch: boolean;
  pickLineup: (lineup: LineupTile) => void;
};

// Desktop: the Line-ups band

/** The Line-ups band: the line-ups as tiles, and once one is on, its day as a time strip with
 * the needle moving with the clock. */
export function LineupBand({ now, canSwitch, pickLineup }: Props) {
  const minute = useOfficeMinute(now);
  const on = lineupOn(now);
  const [listing, setListing] = useState(false);
  const strip = !!on && !!now && minute !== null && !listing;
  const lineups = now?.lineups ?? [];

  return (
    <section className={n.band} aria-labelledby="band-lineups">
      <div className={n.bandTop}>
        {strip && (
          <button
            type="button"
            aria-label="All line-ups"
            className={n.bandBack}
            onClick={() => setListing(true)}
          >
            <Icon name="back" size={18} />
          </button>
        )}
        <h2 id="band-lineups" className={`${n.bandLabel} ${on ? n.bandOn : ""}`}>
          Line-ups
        </h2>
        <span className={n.bandNote}>
          {strip ? `${on.name} · by the clock` : "Line-ups · the one on first"}
        </span>
        {on && <span className={n.pill}>On air</span>}
        {canSwitch && (
          <Link to="/lineups" className={n.bandLink}>
            All line-ups
            <Icon name="chevronRight" size={14} />
          </Link>
        )}
      </div>

      {strip ? (
        <TimeStrip lineup={on} now={now} minute={minute} />
      ) : (
        <div className={n.strip}>
          {lineups.map((lineup) => (
            <LineupTileButton
              key={lineup.id}
              lineup={lineup}
              onPick={
                lineup.on
                  ? () => setListing(false)
                  : canSwitch
                    ? () => {
                        setListing(false);
                        pickLineup(lineup);
                      }
                    : undefined
              }
            />
          ))}
          {now && lineups.length === 0 && (
            <p className={n.emptyTile}>
              No line-ups yet. A line-up plans the day: shows and playlists by the clock.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function LineupTileButton({ lineup, onPick }: { lineup: LineupTile; onPick?: () => void }) {
  const content = (
    <>
      <LineupCover url={lineup.art_url} className={n.cover} />
      <span className={n.tileText}>
        <span className={n.tileName}>{lineup.name}</span>
        <span className={n.tileCaption}>{summary(lineup.slots)}</span>
      </span>
      <span className={n.tileFoot}>
        <span className={lineup.on ? n.onAirText : n.tileCaption}>
          {lineup.on ? "On air · see the day" : lastOn(lineup)}
        </span>
      </span>
      {lineup.on && <span aria-hidden="true" className={n.needle} />}
    </>
  );
  const className = `${n.tile} ${lineup.on ? `${n.on} ${n.glow}` : ""}`;
  return onPick ? (
    <button type="button" className={`${className} ${n.pickable}`} onClick={onPick}>
      {content}
    </button>
  ) : (
    <div className={className}>{content}</div>
  );
}

function TimeStrip({ lineup, now, minute }: { lineup: LineupTile; now: NowState; minute: number }) {
  const { onNow, rest } = upcoming(lineup, now, minute);
  const from = rest[0]?.start ?? now.day.start;
  const hours = [];
  for (let hour = Math.ceil(from / 60) * 60; hour <= now.day.end; hour += 60) hours.push(hour);
  const x = (at: number) => Math.round((at - from) * PX);

  return (
    <>
      <div className={n.timeStrip}>
        <div className={n.timeTrack} style={{ width: x(now.day.end) + 10 }}>
          {rest.map((stretch, index) => {
            const live = onNow && index === 0;
            const tag = live ? "On now" : onNow && index === 1 ? "Next" : clock(stretch.start);
            return (
              <div
                key={stretch.start}
                className={`${n.slotTile} ${stretch.slot ? "" : n.slotGap} ${live ? `${n.on} ${n.glow}` : ""}`}
                style={{ left: x(stretch.start), width: x(stretch.end) - x(stretch.start) - 10 }}
              >
                <span className={`${n.slotTag} ${live ? n.slotTagOn : ""}`}>{tag}</span>
                <span className={n.slotHead}>
                  <SlotArt stretch={stretch} />
                  <span className={n.slotText}>
                    <span className={n.tileName}>{stretch.slot?.name ?? now.gap}</span>
                    <span className={n.tileCaption}>{slotMeta(stretch.slot)}</span>
                  </span>
                </span>
                <span className={n.slotTimes}>
                  {clock(stretch.start)} to {clock(stretch.end)}
                </span>
              </div>
            );
          })}
          <span aria-hidden="true" className={n.ticks} style={{ backgroundSize: `${15 * PX}px 10px` }} />
          {hours.map((hour) => (
            <span key={hour}>
              <span aria-hidden="true" className={n.hourTick} style={{ left: x(hour) }} />
              <span className={n.hourLabel} style={{ left: x(hour) }}>
                {clock(hour)}
              </span>
            </span>
          ))}
          {onNow && (
            <>
              <span aria-hidden="true" className={n.timeNeedle} style={{ left: x(minute) }} />
              <span className={n.stripNow} style={{ left: x(minute) }}>
                Now {clock(Math.floor(minute))}
              </span>
            </>
          )}
        </div>
      </div>
      <p className={n.stripNote}>
        {onNow
          ? "Requests still play first, so a show can start up to a song late. Shows open with their ident and their DJ."
          : "Outside playback hours. The line-up carries on when GuildFM opens again."}
      </p>
    </>
  );
}

// Phone: the Line-ups tab

/** The Line-ups tab: the line-ups as a list, and once one is on, its day running down the
 * screen with "now" marked in the slot on now. */
export function LineupTab({ now, canSwitch, pickLineup }: Props) {
  const minute = useOfficeMinute(now);
  const on = lineupOn(now);
  const [listing, setListing] = useState(false);
  const lineups = now?.lineups ?? [];

  if (on && now && minute !== null && !listing) {
    const { onNow, rest } = upcoming(on, now, minute);
    return (
      <>
        <div className={n.dayTop}>
          <button type="button" className={n.dayBack} onClick={() => setListing(true)}>
            <Icon name="back" size={16} />
            All line-ups
          </button>
          <span className={n.dayName}>{on.name}</span>
          <span className={n.pill}>On air</span>
        </div>
        <ol className={n.dayList}>
          {rest.map((stretch, index) => {
            const live = onNow && index === 0;
            const percent = live
              ? Math.round(((minute - stretch.start) / (stretch.end - stretch.start)) * 100)
              : 0;
            return (
              <li key={stretch.start} className={n.dayRow}>
                <span className={`${n.dayTime} ${live ? n.dayTimeOn : ""}`}>
                  {clock(stretch.start)}
                </span>
                <div
                  className={`${n.dayCard} ${stretch.slot ? "" : n.slotGap} ${live ? `${n.on} ${n.glow}` : ""}`}
                >
                  <span className={n.slotHead}>
                    <SlotArt stretch={stretch} />
                    <span className={n.slotText}>
                      <span className={n.tileName}>{stretch.slot?.name ?? now.gap}</span>
                      <span className={n.tileCaption}>{slotMeta(stretch.slot)}</span>
                    </span>
                    {(live || (onNow && index === 1)) && (
                      <span className={`${n.slotTag} ${live ? n.slotTagOn : ""}`}>
                        {live ? "On now" : "Next"}
                      </span>
                    )}
                  </span>
                  {live && (
                    <span className={n.dayProgress}>
                      <span className={n.dayTrack}>
                        <span className={n.dayFill} style={{ width: `${percent}%` }} />
                        <span
                          aria-hidden="true"
                          className={n.dayNeedle}
                          style={{ left: `${percent}%` }}
                        />
                      </span>
                      <span className={n.dayTimes}>
                        <span>{clock(stretch.start)}</span>
                        <span className={n.dayNow}>Now {clock(Math.floor(minute))}</span>
                        <span>{clock(stretch.end)}</span>
                      </span>
                    </span>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
        <p className={n.hint}>Requests still play first, so a show can start up to a song late.</p>
        {canSwitch && <EditLink />}
      </>
    );
  }

  return (
    <>
      <span className={n.bandNote}>Line-ups · the one on first</span>
      <ul className={n.list}>
        {lineups.map((lineup) => {
          const onPick = lineup.on
            ? () => setListing(false)
            : canSwitch
              ? () => {
                  setListing(false);
                  pickLineup(lineup);
                }
              : undefined;
          const content = (
            <>
              <LineupCover url={lineup.art_url} className={n.cover} iconSize={22} />
              <span className={n.rowText}>
                <span className={n.rowName}>{lineup.name}</span>
                <span className={n.rowCaption}>{summary(lineup.slots)}</span>
              </span>
              <span className={lineup.on ? n.onAirText : n.rowCaption}>{lastOn(lineup)}</span>
            </>
          );
          const className = `${n.row} ${lineup.on ? `${n.on} ${n.glow}` : ""}`;
          return (
            <li key={lineup.id}>
              {onPick ? (
                <button type="button" className={`${className} ${n.pickable}`} onClick={onPick}>
                  {content}
                </button>
              ) : (
                <div className={className}>{content}</div>
              )}
            </li>
          );
        })}
      </ul>
      {now && lineups.length === 0 && (
        <p className={n.emptyRow}>No line-ups yet. A line-up plans the day by the clock.</p>
      )}
      {canSwitch && <EditLink />}
    </>
  );
}

function EditLink() {
  return (
    <Link to="/lineups" className={n.editLineups}>
      Edit line-ups
      <Icon name="chevronRight" size={16} />
    </Link>
  );
}

/** For the other bands: "On now, in Office Day", or null when the line-up isn't playing it. */
export function inLineupCaption(now: NowState | null, inLineup: boolean): string | null {
  const on = lineupOn(now);
  return on && inLineup ? `On now, in ${on.name}` : null;
}
