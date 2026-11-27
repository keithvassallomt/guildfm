import {
  type CSSProperties,
  type MouseEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { api, errorText, type Favourite, type QueueEntry, type QueueState, type SearchTrack } from "../api";
import { Icon } from "../components/Icon";
import { Logo } from "../components/Logo";
import { ownClip } from "../live/status";
import { clock, usePlayback } from "../live/usePlayback";
import { useQueue } from "../live/useQueue";
import { bigArt, QR_PATH } from "./art";
import k from "./Kiosk.module.css";
import { Picker } from "./Picker";

/** 1rem on the kiosk: a 108th of a portrait screen's width, 10 px on the 22-inch (1080 wide). */
const ROOT_SIZE = "min(calc(min(100vw, 75vh) / 108), calc(100vh / 192))";
/** A song that joined Best Voted this recently is celebrated when the kiosk sees it. */
const JUST_JOINED_MS = 20_000;
const STAR = "M12 2.5l2.9 6.1 6.6.8-4.9 4.6 1.3 6.6L12 17.3l-5.9 3.3 1.3-6.6L2.5 9.4l6.6-.8z";

type Box = { x: number; y: number; w: number; h: number };
type Flight = { id: number; kind: "add" | "next"; art: string | null; from: Box; to: Box };
type Burst = { id: number; x: number; y: number; colours: string[]; count: number; reach: number };
type Flash = { id: number; entry: number; kind: "up" | "down" };
type Party = { id: number; title: string; line: string };

let serial = 0;
const next = () => ++serial;

function reducedMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

function titleSize(title: string): string {
  return title.length <= 12 ? "8.8rem" : title.length <= 20 ? "6.8rem" : "5.2rem";
}

function ordinal(n: number): string {
  const tens = n % 100;
  const suffix = ["th", "st", "nd", "rd"][(tens - 20) % 10] ?? ["th", "st", "nd", "rd"][tens] ?? "th";
  return `${n}${tens >= 11 && tens <= 13 ? "th" : suffix}`;
}

function minutesText(seconds: number): string {
  const words = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
  const minutes = Math.round(seconds / 60);
  return `${words[minutes] ?? minutes}-minute`;
}

/** Who put a song on, as the kiosk says it. */
function byLine(entry: QueueEntry): string {
  if (entry.mine) return "Added at the kiosk";
  if (entry.requested_by) return `Requested by ${entry.requested_by.display_name}`;
  if (entry.playlist) return `From ${entry.playlist}`;
  if (entry.station) return `On ${entry.station}`;
  return "";
}

/** The kiosk's screen: Cover Wall. The song that's playing spins on a record; the queue is a wall
 * of covers to vote on; one big button adds a song. */
export default function Kiosk() {
  const { queue, apply, refresh } = useQueue();
  const { state: playback, receivedAt } = usePlayback();
  const root = useRef<HTMLDivElement>(null);
  const label = useRef<HTMLDivElement>(null);
  const addIcon = useRef<HTMLSpanElement>(null);
  const [, setTick] = useState(0);
  const [favourites, setFavourites] = useState<Favourite[]>([]);
  const [picker, setPicker] = useState(false);
  const [flight, setFlight] = useState<Flight | null>(null);
  const [bursts, setBursts] = useState<Burst[]>([]);
  const [flashes, setFlashes] = useState<Flash[]>([]);
  const [ripples, setRipples] = useState<{ id: number; x: number; y: number }[]>([]);
  const [leaving, setLeaving] = useState<Set<number>>(new Set());
  const [gulps, setGulps] = useState(0);
  const [back, setBack] = useState(0);
  const [toast, setToast] = useState<{ id: number; text: string } | null>(null);
  const [party, setParty] = useState<Party | null>(null);
  // While a new song comes on: the one going off, shown until the next one's cover lands.
  const [change, setChange] = useState<{ phase: "out" | "in"; old: QueueEntry | null } | null>(null);
  const [changes, setChanges] = useState(0);
  const skew = useRef(0); // the server's clock minus this one
  const rects = useRef(new Map<number, DOMRect>());
  const order = useRef("");
  const playingBefore = useRef<QueueEntry | null | undefined>(undefined);
  const celebrated = useRef(new Set<string>());
  const wasOnBreak = useRef(false);

  // The kiosk's own sizing, for as long as it's open.
  useEffect(() => {
    const html = document.documentElement;
    const before = html.style.fontSize;
    html.style.fontSize = ROOT_SIZE;
    return () => {
      html.style.fontSize = before;
    };
  }, []);

  // Countdowns and the song's progress.
  useEffect(() => {
    const timer = window.setInterval(() => setTick((tick) => tick + 1), 250);
    return () => window.clearInterval(timer);
  }, []);

  const loadFavourites = useCallback(() => {
    api<Favourite[]>("GET", "/queue/favourites")
      .then(setFavourites)
      .catch(() => {});
  }, []);
  useEffect(loadFavourites, [loadFavourites]);

  const say = (text: string) => {
    const id = next();
    setToast({ id, text });
    window.setTimeout(() => setToast((shown) => (shown?.id === id ? null : shown)), 3500);
  };

  const box = (rect: DOMRect): Box => {
    const at = root.current!.getBoundingClientRect();
    return { x: rect.left - at.left, y: rect.top - at.top, w: rect.width, h: rect.height };
  };

  const burst = (rect: DOMRect, colours: string[], count: number, reach: number) => {
    if (reducedMotion() || !root.current) return;
    const at = box(rect);
    const id = next();
    setBursts((all) => [...all, { id, x: at.x + at.w / 2, y: at.y + at.h / 2, colours, count, reach }]);
    window.setTimeout(() => setBursts((all) => all.filter((b) => b.id !== id)), 850);
  };

  const wall = queue ? ([queue.next, ...queue.waiting].filter(Boolean) as QueueEntry[]) : [];

  // Each time the queue changes: the wall glides into its new order, a new song comes on with
  // its cover lifting off the wall onto the record, and a song that just made Best Voted is
  // celebrated.
  useLayoutEffect(() => {
    if (!queue || !root.current) return;
    if (queue.kiosk) skew.current = Date.parse(queue.kiosk.now) - Date.now();
    loadFavourites();
    const before = rects.current;
    const cards = Array.from(root.current.querySelectorAll<HTMLElement>("[data-card]"));
    const now = new Map(cards.map((card) => [Number(card.dataset.card), card.getBoundingClientRect()]));
    const key = wall.map((entry) => entry.id).join(",");
    if (order.current && key !== order.current && !reducedMotion()) {
      for (const card of cards) {
        const was = before.get(Number(card.dataset.card));
        const is = now.get(Number(card.dataset.card));
        if (!was || !is) continue;
        const dx = was.left - is.left;
        const dy = was.top - is.top;
        if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
          card.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }], {
            duration: 560,
            easing: "cubic-bezier(.2,.8,.2,1)",
          });
        }
      }
    }
    order.current = key;
    rects.current = now;

    const playing = queue.playing;
    const old = playingBefore.current;
    playingBefore.current = playing;
    if (old !== undefined && old?.id !== playing?.id && playing) {
      const from = before.get(playing.id);
      const to = label.current?.getBoundingClientRect();
      if (from && to && !reducedMotion()) {
        const id = next();
        setChange({ phase: "out", old });
        setFlight({ id, kind: "next", art: bigArt(playing.track.art_url), from: box(from), to: box(to) });
        window.setTimeout(() => {
          setFlight((shown) => (shown?.id === id ? null : shown));
          setChange({ phase: "in", old: null });
          setChanges((n) => n + 1);
          window.setTimeout(() => setChange(null), 700);
        }, 880);
      } else {
        setChange({ phase: "in", old: null });
        setChanges((n) => n + 1);
        window.setTimeout(() => setChange(null), 700);
      }
    }

    const joined = playing?.best_voted_at ? Date.parse(playing.best_voted_at) : null;
    const serverNow = Date.now() + skew.current;
    if (playing && joined && serverNow - joined < JUST_JOINED_MS && !celebrated.current.has(playing.track.id)) {
      celebrated.current.add(playing.track.id);
      const id = next();
      window.setTimeout(() => {
        setParty({
          id,
          title: playing.track.title,
          line: `${playing.track.title} has its ${ordinal(playing.up)} thumbs up. It joins the office favourites.`,
        });
        window.setTimeout(() => setParty((shown) => (shown?.id === id ? null : shown)), 4300);
      }, old?.id !== playing.id ? 1500 : 250);
    }
  }, [queue]);

  const kiosk = queue?.kiosk ?? null;
  const serverNow = Date.now() + skew.current;
  const breakLeft = kiosk?.break_until ? Math.max(0, Date.parse(kiosk.break_until) - serverNow) / 1000 : 0;
  const onBreak = breakLeft > 0;
  useEffect(() => {
    if (wasOnBreak.current && !onBreak) {
      // The break's over: the server frees the places when it's next asked.
      refresh();
      setBack(Date.now());
    }
    wasOnBreak.current = onBreak;
  }, [onBreak, refresh]);
  const comingBack = Date.now() - back < 1600;

  const places = kiosk?.places ?? 8;
  const left = Math.max(0, places - (kiosk?.used ?? 0));
  const breakName = minutesText(kiosk?.break_seconds ?? 180);
  const placesText =
    left === 1
      ? `Last song before a ${breakName} break`
      : left === 2
        ? `2 songs left before a ${breakName} break`
        : `${left} of ${places} songs left from the kiosk`;

  const vote = (entry: QueueEntry, value: 1 | -1, event: MouseEvent<HTMLButtonElement>) => {
    if (onBreak) return;
    const up = value === 1;
    const id = next();
    setFlashes((all) => [...all, { id, entry: entry.id, kind: up ? "up" : "down" }]);
    window.setTimeout(() => setFlashes((all) => all.filter((f) => f.id !== id)), 950);
    const light = root.current?.dataset.theme === "light";
    const colour = up ? "#ff8a3d" : light ? "#2c5fc4" : "#8db4ff";
    burst(event.currentTarget.getBoundingClientRect(), [colour, colour, up ? "#ffd2ad" : "#cfe0ff"], 9, 6.5);
    api<QueueState>("POST", `/queue/${entry.id}/vote`, { value })
      .then(apply)
      .catch((error) => say(errorText(error)));
  };

  const openPicker = (event: MouseEvent<HTMLButtonElement>) => {
    if (onBreak) return;
    if (reducedMotion()) {
      setPicker(true);
      return;
    }
    const at = event.currentTarget.getBoundingClientRect();
    const id = next();
    const x = event.clientX ? event.clientX - at.left : at.width / 2;
    const y = event.clientY ? event.clientY - at.top : at.height / 2;
    setRipples((all) => [...all, { id, x, y }]);
    window.setTimeout(() => setRipples((all) => all.filter((r) => r.id !== id)), 650);
    window.setTimeout(() => setPicker(true), 200);
  };

  // A picked cover flies into the Add button, then the song drops into the wall.
  const pick = async (track: SearchTrack, cover: HTMLElement | null) => {
    if (flight) return;
    setPicker(false);
    const request = api<QueueState>("POST", "/queue", { track_id: track.id });
    const target = addIcon.current;
    if (cover && target && !reducedMotion()) {
      const id = next();
      setFlight({
        id,
        kind: "add",
        art: bigArt(track.art_url),
        from: box(cover.getBoundingClientRect()),
        to: box(target.getBoundingClientRect()),
      });
      await Promise.allSettled([request, new Promise((done) => window.setTimeout(done, 780))]);
      setFlight((shown) => (shown?.id === id ? null : shown));
    }
    try {
      apply(await request);
      if (target) burst(target.getBoundingClientRect(), ["#ff8a3d", "#ffd2ad", "#f5c451", "#fffaf4"], 16, 11);
      setGulps((n) => n + 1);
      window.setTimeout(() => {
        root.current
          ?.querySelector(`[data-track="${track.id}"]`)
          ?.scrollIntoView({ block: "nearest", behavior: reducedMotion() ? "auto" : "smooth" });
      }, 60);
    } catch (error) {
      say(errorText(error));
    }
  };

  const undo = (entry: QueueEntry) => {
    setLeaving((all) => new Set(all).add(entry.id));
    window.setTimeout(() => {
      api<QueueState>("DELETE", `/queue/${entry.id}`)
        .then(apply)
        .catch((error) => say(errorText(error)))
        .finally(() =>
          setLeaving((all) => {
            const rest = new Set(all);
            rest.delete(entry.id);
            return rest;
          }),
        );
    }, reducedMotion() ? 0 : 300);
  };

  const light = kiosk?.theme === "light";
  const hero = change?.phase === "out" ? change.old : (queue?.playing ?? null);
  const talking = !!playback && ownClip(playback);
  const track = playback?.track;
  const ours = !!track?.ours && !!hero;
  const position = track
    ? Math.min(
        track.duration,
        track.position + (playback?.status === "playing" ? (performance.now() - receivedAt) / 1000 : 0),
      )
    : 0;
  const heroArt = bigArt(hero?.track.art_url ?? (ours ? null : (track?.art_url ?? null)));
  const heading = playback?.announcing
    ? "ANNOUNCEMENT"
    : playback?.dj_talking
      ? "THE DJ IS ON"
      : playback?.jingle
        ? "JINGLE"
        : "NOW PLAYING";

  return (
    <div ref={root} className={k.kiosk} data-theme={light ? "light" : "dark"}>
      <div aria-hidden="true" key={changes} className={`${k.backdrop} ${changes ? k.backdropIn : ""}`}>
        {heroArt && (
          <div className={k.wash}>
            <img src={heroArt} alt="" />
          </div>
        )}
        <div className={k.record}>
          <div className={k.grooves} />
          <div className={k.grain} />
          <div className={k.recordSheen} />
          <div className={k.runout} />
        </div>
      </div>
      <div aria-hidden="true" className={k.fade} />

      <header className={k.header}>
        <Logo className={k.logo} />
        {party ? (
          <span className={k.bestChip}>
            <Star />
            BEST VOTED
          </span>
        ) : (
          <span className={k.onAir}>{heading}</span>
        )}
      </header>

      <section aria-label="Now playing" className={k.hero}>
        <div className={k.heroRow}>
          {hero && !change ? (
            <Thumb entry={hero} kind="down" round votes={kiosk?.votes ?? 2} paused={onBreak} flashes={flashes} onVote={vote} />
          ) : (
            <span className={`${k.thumb} ${k.round}`} style={{ visibility: "hidden" }} />
          )}
          <div
            ref={label}
            className={[
              k.label,
              change?.phase === "out" ? k.labelOut : "",
              change?.phase === "in" ? k.labelIn : "",
              party && !change ? k.labelGold : "",
            ].join(" ")}
          >
            {talking || !heroArt ? (
              <span className={k.labelLogo}>
                <Logo />
              </span>
            ) : (
              <div className={k.labelSpin}>
                <WholeCover art={heroArt} />
              </div>
            )}
            <span aria-hidden="true" className={k.labelSheen} />
            <span aria-hidden="true" className={k.spindle} />
            {hero?.best_voted_at && !talking && (
              <span className={k.labelBadge}>
                <Star />
                BEST VOTED
              </span>
            )}
          </div>
          {hero && !change ? (
            <Thumb entry={hero} kind="up" round votes={kiosk?.votes ?? 2} paused={onBreak} flashes={flashes} onVote={vote} />
          ) : (
            <span className={`${k.thumb} ${k.round}`} style={{ visibility: "hidden" }} />
          )}
        </div>
        <div
          className={`${k.heroText} ${change?.phase === "out" ? k.textOut : change?.phase === "in" ? k.textIn : ""}`}
        >
          <span className={k.title} style={{ fontSize: titleSize(hero?.track.title ?? track?.title ?? "") }}>
            {hero?.track.title ?? (track?.title || "Nothing on just now")}
          </span>
          <span className={k.artist}>
            {hero?.track.artists ?? (track ? track.artist : "Add a song to get it going")}
          </span>
          {hero && <span className={k.by}>{byLine(hero)}</span>}
        </div>
        {track && track.duration > 0 && (
          <div className={k.progress}>
            <span>{clock(position)}</span>
            <div className={k.progressTrack}>
              <div
                className={k.progressFill}
                style={{
                  width: `${(position / track.duration) * 100}%`,
                  transition: change ? "none" : "width 0.25s linear",
                }}
              />
            </div>
            <span className={k.length}>{clock(track.duration)}</span>
          </div>
        )}
      </section>

      <section aria-label="Up next" className={k.wall}>
        <div className={k.wallHead}>
          <h2 className={k.wallTitle}>Up next</h2>
          <span className={k.wallHint}>
            Tap a thumb to vote. The kiosk gets {kiosk?.votes === 1 ? "one vote" : "two votes"} a song.
          </span>
        </div>
        <div className={`${k.wallScroll} ${onBreak ? k.wallDim : ""}`}>
          {wall.length === 0 ? (
            <p className={k.empty}>Nothing's waiting. Tap Add a song to pick the next one.</p>
          ) : (
            <div className={k.grid}>
              {wall.map((entry, index) => {
                const until = entry.undo_until ? Date.parse(entry.undo_until) : 0;
                const fresh = until > serverNow && !leaving.has(entry.id);
                const secs = Math.ceil((until - serverNow) / 1000);
                const locked = entry.state === "next";
                return (
                  <div
                    key={entry.id}
                    data-card={entry.id}
                    data-track={entry.track.id}
                    className={[
                      k.card,
                      leaving.has(entry.id) ? k.cardOut : fresh ? k.cardIn : "",
                      flight?.kind === "next" && queue?.playing?.id === entry.id ? k.cardLifted : "",
                    ].join(" ")}
                  >
                    <div className={`${k.cover} ${fresh ? k.coverFresh : ""}`}>
                      {entry.track.art_url && <img src={bigArt(entry.track.art_url) ?? undefined} alt="" />}
                      <span className={k.place}>{index + 1}</span>
                      {locked ? (
                        <span className={k.mark}>
                          <Icon name="lock" size={18} />
                          NEXT
                        </span>
                      ) : (
                        entry.mine && !fresh && <span className={k.mark}>KIOSK</span>
                      )}
                      {fresh ? (
                        <button
                          type="button"
                          className={k.undo}
                          onClick={() => undo(entry)}
                          aria-label={`Undo adding ${entry.track.title}, ${secs} seconds left`}
                        >
                          <span className={k.ring}>
                            <svg viewBox="0 0 36 36" aria-hidden="true">
                              <circle cx="18" cy="18" r="15" fill="none" className={k.ringTrack} strokeWidth="3.5" />
                              <circle
                                cx="18"
                                cy="18"
                                r="15"
                                fill="none"
                                className={k.ringLeft}
                                strokeWidth="3.5"
                                strokeLinecap="round"
                                strokeDasharray="94.25"
                                strokeDashoffset={94.25 * (1 - Math.max(0, until - serverNow) / ((kiosk?.undo_seconds ?? 10) * 1000))}
                              />
                            </svg>
                            {secs}
                          </span>
                          Undo
                        </button>
                      ) : (
                        !locked &&
                        !leaving.has(entry.id) && (
                          <div className={k.pills}>
                            <Thumb entry={entry} kind="up" votes={kiosk?.votes ?? 2} paused={onBreak} flashes={flashes} onVote={vote} />
                            <Thumb entry={entry} kind="down" votes={kiosk?.votes ?? 2} paused={onBreak} flashes={flashes} onVote={vote} />
                          </div>
                        )
                      )}
                    </div>
                    <div className={k.cardText}>
                      <span className={k.cardTitle}>{entry.track.title}</span>
                      <span className={k.cardArtist}>{entry.track.artists}</span>
                      <span className={`${k.cardBy} ${fresh ? k.cardByFresh : ""}`}>
                        {fresh ? `Just added · ${ordinal(index + 1)} in line` : byLine(entry)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {onBreak && (
          <div aria-live="polite" className={k.breakCard}>
            <span className={k.breakLabel}>
              <span className={k.breakDot} />
              KIOSK BREAK
            </span>
            <span className={k.breakClock}>{clock(Math.ceil(breakLeft))}</span>
            <span className={k.breakUntil}>until you can add songs and vote here again</span>
            <span className={k.rule} />
            <p className={k.breakText}>
              The kiosk has added {places} songs, so it's taking a {breakName} break. They're all on
              the wall and will play in turn with everyone else's.
            </p>
            <BreakUndo wall={wall} serverNow={serverNow} onUndo={undo} />
          </div>
        )}
      </section>

      <footer className={k.footer}>
        {onBreak ? (
          <div role="timer" aria-label={`Kiosk break, back in ${clock(Math.ceil(breakLeft))}`} className={k.breakBar}>
            <BarFace clockText={clock(Math.ceil(breakLeft))} />
            <BarFace
              clockText={clock(Math.ceil(breakLeft))}
              top
              clip={`inset(0 ${(1 - breakLeft / (kiosk?.break_seconds ?? 180)) * 100}% 0 0)`}
            />
          </div>
        ) : (
          <button
            type="button"
            className={`${k.add} ${comingBack ? k.back : gulps ? (gulps % 2 ? k.gulpA : k.gulpB) : ""}`}
            onClick={openPicker}
          >
            {ripples.map((ripple) => (
              <span key={ripple.id} className={k.ripple} style={{ left: ripple.x, top: ripple.y }} />
            ))}
            {comingBack && <span aria-hidden="true" className={k.shine} />}
            <span ref={addIcon} className={k.addIcon}>
              <Icon name="plus" strokeWidth={2.6} />
            </span>
            <span className={k.addText}>
              <span className={k.addTitle}>Add a song</span>
              <span className={`${k.addPlaces} ${left <= 2 ? k.addWarn : ""}`}>{placesText}</span>
            </span>
            <span aria-hidden="true" className={k.dots}>
              {Array.from({ length: places }, (_, index) => (
                <span key={index} className={`${k.dot} ${index >= left ? k.dotUsed : ""}`} />
              ))}
            </span>
          </button>
        )}
        <div className={k.qr}>
          <div className={k.qrTile}>
            <svg viewBox="-1 -1 27 27" role="img" aria-label="QR code for guildfm.com" shapeRendering="crispEdges">
              <rect x="-1" y="-1" width="27" height="27" fill="currentColor" style={{ color: "var(--k-qr-bg)" }} />
              <path fill="#1a0e05" d={QR_PATH} />
            </svg>
          </div>
          <span className={k.qrCaption}>{onBreak ? "Use your phone" : "Your name on it"}</span>
        </div>
      </footer>

      {picker && !onBreak && (
        <Picker
          favourites={favourites}
          playingId={queue?.playing?.track.id ?? null}
          places={placesText}
          warn={left <= 2}
          onPick={pick}
          onClose={() => setPicker(false)}
        />
      )}

      {party && <Celebration party={party} />}
      {flight && <Flying flight={flight} />}
      {bursts.map((b) => (
        <BurstAt key={b.id} burst={b} />
      ))}
      {toast && (
        <div key={toast.id} role="status" className={k.toast}>
          {toast.text}
        </div>
      )}
    </div>
  );
}

function Star() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d={STAR} />
    </svg>
  );
}

const MIRRORED = [-1, 0, 1].flatMap((dy) =>
  [-1, 0, 1].map((dx) => ({
    left: `${dx * 100}%`,
    top: `${dy * 100}%`,
    transform: `scale(${dx ? -1 : 1}, ${dy ? -1 : 1})`,
  })),
);

/** The whole square cover inside the round label, its edges fading into a blurred copy of itself,
 * mirrored on every side so its colours run on past each edge. */
function WholeCover({ art, style }: { art: string; style?: CSSProperties }) {
  return (
    <>
      <div className={`${k.fit} ${k.fitBlur}`} style={style}>
        {MIRRORED.map((at, index) => (
          <img key={index} src={art} alt="" className={k.mirror} style={at} />
        ))}
      </div>
      <img src={art} alt="" className={`${k.fit} ${k.soft} ${k.fitImg}`} style={style} />
    </>
  );
}

type ThumbProps = {
  entry: QueueEntry;
  kind: "up" | "down";
  round?: boolean;
  votes: number;
  paused: boolean;
  flashes: Flash[];
  onVote: (entry: QueueEntry, value: 1 | -1, event: MouseEvent<HTMLButtonElement>) => void;
};

/** A thumb the kiosk can tap up to `votes` times on a song. Its dots are the taps it has left. */
function Thumb({ entry, kind, round, votes, paused, flashes, onVote }: ThumbProps) {
  const up = kind === "up";
  const mine = up ? entry.kiosk_up : entry.kiosk_down;
  const spent = mine >= votes;
  const word = up ? "thumbs up" : "thumbs down";
  const leftVotes = votes - mine;
  return (
    <button
      type="button"
      disabled={spent || paused}
      onClick={(event) => onVote(entry, up ? 1 : -1, event)}
      aria-label={
        spent
          ? `The kiosk has given ${entry.track.title} both its ${word}`
          : `Give ${entry.track.title} a ${up ? "thumbs up" : "thumbs down"}, ${up ? entry.up : entry.down} so far. The kiosk has ${leftVotes} ${leftVotes === 1 ? "vote" : "votes"} left on it`
      }
      className={[
        k.thumb,
        round ? k.round : k.pill,
        mine > 0 ? (up ? k.up : k.down) : "",
        mine > 0 ? (mine % 2 ? k.popA : k.popB) : "",
        spent ? k.spent : "",
        paused ? k.paused : "",
      ].join(" ")}
    >
      <Icon name={up ? "thumbUp" : "thumbDown"} filled={mine > 0} strokeWidth={round ? 1.8 : 2} />
      <span className={k.count}>{up ? entry.up : entry.down}</span>
      <span className={k.pips}>
        {Array.from({ length: votes }, (_, index) => (
          <span key={index} className={`${k.pip} ${index >= votes - mine ? k.pipUsed : ""}`} />
        ))}
      </span>
      {flashes
        .filter((flash) => flash.entry === entry.id && flash.kind === kind)
        .map((flash) => (
          <span key={flash.id} className={`${k.plusOne} ${up ? k.plusUp : k.plusDown}`}>
            +1
          </span>
        ))}
    </button>
  );
}

/** During a break, the request that started it can still be taken back for a moment. */
function BreakUndo({ wall, serverNow, onUndo }: { wall: QueueEntry[]; serverNow: number; onUndo: (entry: QueueEntry) => void }) {
  const fresh = wall.find((entry) => entry.undo_until && Date.parse(entry.undo_until) > serverNow);
  if (!fresh) return null;
  const secs = Math.ceil((Date.parse(fresh.undo_until!) - serverNow) / 1000);
  return (
    <button type="button" className={k.outlineButton} onClick={() => onUndo(fresh)}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M3 7v6h6" />
        <path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13" />
      </svg>
      Undo {fresh.track.title} ({secs})
    </button>
  );
}

/** One face of the break's bar. The orange one sits on top and is cut back as the break runs
 * down, so the words read the same whichever colour is behind them. */
function BarFace({ clockText, top, clip }: { clockText: string; top?: boolean; clip?: string }) {
  return (
    <div aria-hidden="true" className={`${k.barLayer} ${top ? k.barTop : ""}`} style={clip ? { clipPath: clip } : undefined}>
      <span className={k.barIcon}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M10 2h4" />
          <path d="M12 14l3-3" />
          <circle cx="12" cy="14" r="8" />
        </svg>
      </span>
      <span className={k.barWords}>
        <span className={k.barTitle}>Back in {clockText}</span>
        <span className={k.barNote}>Adding and voting are paused</span>
      </span>
    </div>
  );
}

const ADD_MOVES =
  "left 0.72s cubic-bezier(.5,-0.3,.4,1), top 0.72s cubic-bezier(.4,0,.2,1), width 0.72s cubic-bezier(.6,0,.4,1), height 0.72s cubic-bezier(.6,0,.4,1), border-radius 0.72s ease-in, transform 0.72s ease-in";
const NEXT_MOVES =
  "left 0.82s cubic-bezier(.3,.1,.2,1), top 0.82s cubic-bezier(.6,0,.2,1), width 0.82s cubic-bezier(.3,.1,.2,1), height 0.82s cubic-bezier(.3,.1,.2,1), border-radius 0.82s ease-in-out, transform 0.82s";
const FIT_MOVES =
  "left 0.82s cubic-bezier(.3,.1,.2,1), top 0.82s cubic-bezier(.3,.1,.2,1), width 0.82s cubic-bezier(.3,.1,.2,1), height 0.82s cubic-bezier(.3,.1,.2,1)";

/** A cover on its way: from the picker into the Add button, or off the wall onto the record. */
function Flying({ flight }: { flight: Flight }) {
  const [going, setGoing] = useState(false);
  useLayoutEffect(() => {
    let second = 0;
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => setGoing(true));
    });
    return () => {
      cancelAnimationFrame(first);
      cancelAnimationFrame(second);
    };
  }, []);
  const at = going ? flight.to : flight.from;
  const toRecord = flight.kind === "next";
  const style: CSSProperties = {
    left: at.x,
    top: at.y,
    width: at.w,
    height: at.h,
    borderRadius: going ? "50%" : "2rem",
    transform: going ? (toRecord ? "none" : "rotate(-14deg)") : "scale(1.06)",
    transition: going ? (toRecord ? NEXT_MOVES : ADD_MOVES) : "none",
  };
  // On its way to the record, the cover shrinks to sit whole inside the label.
  const fit: CSSProperties = going
    ? { transition: FIT_MOVES }
    : { left: 0, top: 0, width: "100%", height: "100%", transition: "none" };
  return (
    <div aria-hidden="true" className={k.flight} style={style}>
      {flight.art &&
        (toRecord ? <WholeCover art={flight.art} style={fit} /> : <img src={flight.art} alt="" />)}
    </div>
  );
}

function BurstAt({ burst }: { burst: Burst }) {
  return (
    <span aria-hidden="true" className={k.burst} style={{ left: burst.x, top: burst.y }}>
      {Array.from({ length: burst.count }, (_, index) => {
        const angle = (index / burst.count) * Math.PI * 2 + (index % 2) * 0.35;
        const reach = burst.reach * (0.65 + ((index * 37) % 10) / 22);
        const size = index % 3 === 0 ? 1.6 : 1.1;
        return (
          <span
            key={index}
            className={k.particle}
            style={
              {
                width: `${size}rem`,
                height: `${size}rem`,
                background: burst.colours[index % burst.colours.length],
                "--dx": `${(Math.cos(angle) * reach).toFixed(2)}rem`,
                "--dy": `${(Math.sin(angle) * reach).toFixed(2)}rem`,
              } as CSSProperties
            }
          />
        );
      })}
    </span>
  );
}

const CONFETTI = ["#f5c451", "#ff8a3d", "#fffaf4", "#ffd2ad", "#8db4ff"];

/** A song made it into Best Voted: gold rings from the record, confetti and a banner. */
function Celebration({ party }: { party: Party }) {
  const random = (index: number, salt: number) => {
    const x = Math.sin((party.id * 97.3 + index * 13.37 + salt * 7.1) * 12.9898) * 43758.5453;
    return x - Math.floor(x);
  };
  return (
    <div aria-live="polite" className={k.party}>
      <span className={k.goldRing} />
      <span className={k.goldRing} style={{ animationDelay: "0.35s" }} />
      {Array.from({ length: 46 }, (_, index) => (
        <span
          key={index}
          className={k.confetti}
          style={
            {
              left: `${(random(index, 1) * 100).toFixed(1)}%`,
              width: `${(0.9 + random(index, 2) * 1.1).toFixed(2)}rem`,
              height: `${(1.6 + random(index, 3) * 1.6).toFixed(2)}rem`,
              background: CONFETTI[index % CONFETTI.length],
              "--dx": `${((random(index, 4) - 0.5) * 30).toFixed(1)}rem`,
              "--r": `${Math.round((random(index, 5) - 0.5) * 1440)}deg`,
              "--fall": `${(2.4 + random(index, 6) * 1.6).toFixed(2)}s`,
              "--delay": `${(random(index, 7) * 0.7).toFixed(2)}s`,
            } as CSSProperties
          }
        />
      ))}
      <div className={k.banner}>
        <Star />
        <div className={k.bannerText}>
          <span className={k.bannerTitle}>Into Best Voted!</span>
          <span className={k.bannerLine}>{party.line}</span>
        </div>
      </div>
    </div>
  );
}
