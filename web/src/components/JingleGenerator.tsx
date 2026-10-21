import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  api,
  errorText,
  type DraftStatus,
  type JingleDraft,
  type JingleIdea,
  type JingleRound,
  type StationAsEdited,
} from "../api";
import { clock } from "../live/usePlayback";
import { Button } from "./Button";
import { Dialog } from "./Dialog";
import { Icon } from "./Icon";
import { Stepper } from "./Stepper";
import { FormError } from "./TextField";
import { Toggle } from "./Toggle";
import { useVoices } from "./useVoices";
import styles from "./JingleGenerator.module.css";

const SHORTEST = 5;
const LONGEST = 15;
const MOST = 6; // in a round
const POLL_MS = 2000;

type Card = {
  key: number;
  text: string;
  /** The AI's name for it, if it wrote it; else one comes from the description. */
  name: string;
  /** Written by the AI and not changed since. */
  ai: boolean;
  length: number;
  instrumental: boolean;
  writing: boolean;
};

let nextKey = 1;
const blank = (): Card => ({
  key: nextKey++,
  text: "",
  name: "",
  ai: false,
  length: 8,
  instrumental: false,
  writing: false,
});
const blanks = (count: number) => Array.from({ length: count }, blank);

/** "Soft piano for the afternoon: quiet and short" becomes "Soft piano for the afternoon". */
function nameFrom(text: string): string {
  const words = text.split(/[:.,;!?]/)[0].trim().split(/\s+/).slice(0, 5).join(" ");
  return (words ? words.charAt(0).toUpperCase() + words.slice(1) : "Jingle").slice(0, 100);
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const undecided = (draft: JingleDraft) =>
  draft.status === "making" || draft.status === "ready" || draft.status === "failed";

type Props = {
  open: boolean;
  onClose: () => void;
  /** A station's own idents, or the system idents for null. */
  stationId: number | null;
  /** The station as its editor has it, saved or not, for the AI to write from. */
  station?: StationAsEdited;
  /** The jingles changed: one was kept, or that was undone. */
  onChanged: () => void;
};

/**
 * The jingle generator: describe jingles, or have the AI write them, then ElevenLabs makes them
 * to listen to and keep or turn down. A round left part way is still there when it's opened
 * again; Done ends it.
 */
export function JingleGenerator({ open, onClose, stationId, station, onChanged }: Props) {
  const [step, setStep] = useState<"describe" | "review" | null>(null); // null while loading
  const [cards, setCards] = useState<Card[]>(() => blanks(3));
  const [round, setRound] = useState<JingleRound | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [busy, setBusy] = useState<number | null>(null); // a draft with a request in flight
  const [confirming, setConfirming] = useState(false);
  const [names, setNames] = useState<Record<number, string>>({}); // being typed
  const [fixes, setFixes] = useState<Record<number, string>>({}); // refused ones, rewritten
  const [playing, setPlaying] = useState<{ id: number; at: number } | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const voices = useVoices();
  const ready = voices?.elevenlabs_ready ?? true;
  const ids = useId();
  const query = stationId === null ? "" : `?station_id=${stationId}`;
  const system = stationId === null;
  // The editor's details, once there's enough to go on; otherwise the saved ones.
  const asEdited = station && station.name.trim() && station.description.trim() ? station : null;

  const load = useCallback(async () => {
    const found = await api<JingleRound>("GET", `/jingles/drafts${query}`);
    setRound(found);
    return found;
  }, [query]);

  const stop = useCallback(() => {
    audio.current?.pause();
    audio.current = null;
    setPlaying(null);
  }, []);
  useEffect(() => stop, [stop]);

  // Opening picks up a round left part way, or starts a new one.
  useEffect(() => {
    if (!open) {
      stop();
      return;
    }
    setError(null);
    setConfirming(false);
    setStep(null);
    load()
      .then((found) => {
        if (found.drafts.length === 0) setCards(blanks(3));
        setStep(found.drafts.length ? "review" : "describe");
      })
      .catch((caught) => {
        setError(errorText(caught));
        setStep("describe");
      });
  }, [open, load, stop]);

  // While ElevenLabs is making any, look again every couple of seconds.
  const making = round?.drafts.some((draft) => draft.status === "making") ?? false;
  useEffect(() => {
    if (!open || !making) return;
    const timer = window.setInterval(() => load().catch(() => {}), POLL_MS);
    return () => window.clearInterval(timer);
  }, [open, making, load]);

  const update = (key: number, change: Partial<Card>) =>
    setCards((all) => all.map((card) => (card.key === key ? { ...card, ...change } : card)));

  const resize = (count: number) =>
    setCards((all) => [...all.slice(0, count), ...blanks(Math.max(0, count - all.length))]);

  /** The AI's descriptions for the cards numbered `asked`, from the rest of the round too. It
   * only writes an instrumental for a card switched to one. */
  const ideas = (round: { text: string; instrumental: boolean }[], asked: number[]) =>
    api<JingleIdea[]>("POST", "/jingles/ideas", {
      station_id: stationId,
      station: asEdited,
      cards: round,
      write: asked,
    });

  const write = async (asked: number[]) => {
    const keys = asked.map((n) => cards[n].key);
    setError(null);
    setCards((all) => all.map((card) => (keys.includes(card.key) ? { ...card, writing: true } : card)));
    try {
      const found = await ideas(
        cards.map(({ text, instrumental }) => ({ text, instrumental })),
        asked,
      );
      setCards((all) =>
        all.map((card) => {
          const idea = found[keys.indexOf(card.key)];
          if (!idea) return card;
          return {
            ...card,
            writing: false,
            ai: true,
            text: idea.prompt,
            name: idea.name,
            length: idea.seconds,
          };
        }),
      );
    } catch (caught) {
      setError(errorText(caught));
      setCards((all) => all.map((card) => (keys.includes(card.key) ? { ...card, writing: false } : card)));
    }
  };

  const generate = async () => {
    setSending(true);
    setError(null);
    try {
      for (const card of cards) {
        await api<JingleDraft>("POST", "/jingles/drafts", {
          station_id: stationId,
          name: card.name || nameFrom(card.text),
          prompt: card.text.trim(),
          length: card.length,
          instrumental: card.instrumental,
        });
      }
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setSending(false);
    }
    const found = await load().catch(() => null);
    if (found?.drafts.length) setStep("review");
  };

  /** A request about one draft, then the round as it is now. */
  const act = async (draft: JingleDraft, request: () => Promise<unknown>, changesList = false) => {
    setBusy(draft.id);
    setError(null);
    try {
      await request();
      if (changesList) onChanged();
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(null);
    }
    const found = await load().catch(() => null);
    if (found && found.drafts.length === 0) {
      setCards(blanks(3));
      setStep("describe");
    }
  };

  const decide = (draft: JingleDraft, status: DraftStatus) => {
    if (playing?.id === draft.id) stop();
    const name = (names[draft.id] ?? draft.name).trim();
    const body = status === "kept" && name ? { status, name } : { status };
    // Keeping one, or undoing a keep, changes the list.
    const changesList = status === "kept" || draft.status === "kept";
    return act(draft, () => api("PATCH", `/jingles/drafts/${draft.id}`, body), changesList);
  };

  const rename = (draft: JingleDraft) => {
    const name = (names[draft.id] ?? draft.name).trim();
    if (!name || name === draft.name) return;
    act(draft, () => api("PATCH", `/jingles/drafts/${draft.id}`, { name }), draft.status === "kept");
  };

  const again = (draft: JingleDraft) => {
    if (playing?.id === draft.id) stop();
    const prompt = (fixes[draft.id] ?? draft.suggestion ?? draft.prompt).trim();
    const body = prompt && prompt !== draft.prompt ? { prompt } : undefined;
    act(draft, () => api("POST", `/jingles/drafts/${draft.id}/again`, body));
  };

  const leaveOut = (draft: JingleDraft) =>
    act(draft, () => api("DELETE", `/jingles/drafts/${draft.id}`));

  const fix = (draft: JingleDraft) =>
    act(draft, async () => {
      const text = fixes[draft.id] ?? draft.suggestion ?? draft.prompt;
      const [idea] = await ideas([{ text, instrumental: draft.instrumental }], [0]);
      setFixes((all) => ({ ...all, [draft.id]: idea.prompt }));
    });

  const listen = (draft: JingleDraft) => {
    if (playing?.id === draft.id) {
      stop();
      return;
    }
    stop();
    if (!draft.url) return;
    const player = new Audio(draft.url);
    audio.current = player;
    player.ontimeupdate = () => setPlaying({ id: draft.id, at: player.currentTime });
    player.onended = stop;
    setPlaying({ id: draft.id, at: 0 });
    player.play().catch(() => {
      stop();
      setError("Couldn't play that here.");
    });
  };

  /** End the round: kept ones stay, turned down ones are remembered, the rest thrown away. */
  const finish = async (then: "close" | "more") => {
    stop();
    setSending(true);
    setError(null);
    try {
      await api("POST", `/jingles/drafts/done${query}`);
      setConfirming(false);
      setNames({});
      setFixes({});
      if (then === "close") {
        onClose();
        return;
      }
      setCards(blanks(cards.length));
      await load();
      setStep("describe");
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setSending(false);
    }
  };

  const drafts = round?.drafts ?? [];
  const left = drafts.filter(undecided).length;
  const kept = drafts.filter((draft) => draft.status === "kept").length;
  const turnedDown = drafts.filter((draft) => draft.status === "turned_down").length;
  const empties = cards.flatMap((card, n) => (!card.text.trim() && !card.writing ? [n] : []));
  const writing = cards.some((card) => card.writing);
  const canGenerate = ready && !sending && !writing && cards.every((card) => card.text.trim());

  const madeBefore = round ? round.kept + round.turned_down : 0;
  const reads = system ? "About GuildFM" : "the station's name, description and DJ, as the editor has them";
  const context = [
    madeBefore
      ? `The AI reads ${reads}, and the ${plural(madeBefore, "jingle", "jingles")} made here before (${round?.kept} kept, ${round?.turned_down} turned down), so new ones come out different.`
      : `The AI reads ${reads}. Nothing has been made here yet.`,
    "In an empty card it writes a new one, and in one with words in it, it builds on them.",
  ].join(" ");

  let hint = "ElevenLabs makes them from the account's credits, in a minute or so.";
  if (!ready) hint = "ElevenLabs isn't set up, so jingles can't be made. Add ELEVENLABS_API_KEY to .env.";
  else if (writing) hint = "The AI is writing...";
  else if (empties.length === 1) hint = `Fill in jingle ${empties[0] + 1}, or let the AI write it.`;
  else if (empties.length > 1) hint = "Fill in the empty ones, or let the AI write them.";

  const footer =
    step === "describe" ? (
      <div className={styles.foot}>
        <p className={styles.hint}>{hint}</p>
        <Button disabled={!canGenerate} onClick={generate} className={styles.main}>
          {sending ? "Sending..." : `Generate ${plural(cards.length, "jingle", "jingles")}`}
        </Button>
      </div>
    ) : step === "review" && confirming ? (
      <div className={styles.foot}>
        <p className={styles.warn}>
          {plural(left, "jingle", "jingles")} still to decide on. Throw {left === 1 ? "it" : "them"} away?
        </p>
        <div className={styles.buttons}>
          <Button variant="secondary" onClick={() => setConfirming(false)}>
            Keep deciding
          </Button>
          <Button variant="secondary" className={styles.throw} disabled={sending} onClick={() => finish("close")}>
            Throw {left === 1 ? "it" : "them"} away
          </Button>
        </div>
      </div>
    ) : step === "review" ? (
      <div className={styles.foot}>
        <div className={styles.more}>
          <Button variant="secondary" disabled={left > 0 || sending} onClick={() => finish("more")}>
            <Icon name="plus" size={16} strokeWidth={2.4} />
            Generate more
          </Button>
          <span className={styles.tally}>
            {kept} kept · {turnedDown} turned down{left ? ` · ${left} to go` : ""}
          </span>
        </div>
        <Button
          disabled={sending}
          onClick={() => (left ? setConfirming(true) : finish("close"))}
          className={styles.done}
        >
          Done
        </Button>
      </div>
    ) : null;

  return (
    <Dialog open={open} onClose={onClose} title="Generate jingles" tall footer={footer}>
      <p className={styles.for}>
        {system ? "System idents, for every AI station" : `Station idents for ${station?.name.trim() || "this station"}`}
      </p>

      {step === "describe" && (
        <>
          <div className={styles.top}>
            <div className={styles.count}>
              <span className={styles.countLabel} aria-hidden="true">
                How many
              </span>
              <Stepper label="How many jingles" value={cards.length} min={1} max={MOST} onChange={resize} />
            </div>
            <Button variant="secondary" className={styles.aiAll} disabled={empties.length === 0} onClick={() => write(empties)}>
              <Icon name="sparkle" size={18} />
              {empties.length === 1 && cards.length > 1 ? "Write the empty one" : "Write the empty ones"}
            </Button>
          </div>
          <p className={styles.context}>
            <Icon name="info" size={16} />
            <span>{context}</span>
          </p>
          {cards.map((card, n) => (
            <article key={card.key} className={`${styles.card} ${card.writing ? styles.writing : ""}`}>
              <div className={styles.cardHead}>
                <h3 className={styles.cardTitle}>Jingle {n + 1}</h3>
                {card.ai && !card.writing && <span className={styles.chip}>Written by AI</span>}
                <button
                  type="button"
                  className={styles.ai}
                  disabled={card.writing}
                  aria-label={
                    card.writing
                      ? `The AI is writing jingle ${n + 1}`
                      : card.text.trim()
                        ? `Build on jingle ${n + 1} with AI`
                        : `Write jingle ${n + 1} with AI`
                  }
                  onClick={() => write([n])}
                >
                  <span className={card.writing ? styles.pulse : undefined}>
                    <Icon name="sparkle" size={16} />
                  </span>
                  {card.writing ? "Writing..." : "AI"}
                </button>
              </div>
              <textarea
                rows={3}
                maxLength={1000}
                value={card.text}
                disabled={card.writing}
                aria-label={`Describe jingle ${n + 1}`}
                placeholder="Describe it: the style, the instruments, and any words sung or said. Or let the AI write one."
                className={`${styles.textarea} ${card.writing ? styles.pulse : ""}`}
                onChange={(event) =>
                  update(card.key, {
                    text: event.target.value,
                    ai: false,
                    name: event.target.value.trim() ? card.name : "",
                  })
                }
              />
              <div className={styles.cardFoot}>
                <label className={styles.length}>
                  Length
                  <input
                    type="range"
                    min={SHORTEST}
                    max={LONGEST}
                    step={1}
                    value={card.length}
                    disabled={card.writing}
                    className={styles.range}
                    onChange={(event) => update(card.key, { length: Number(event.target.value) })}
                  />
                  <span className={styles.seconds}>{card.length} s</span>
                </label>
                <div className={styles.switch}>
                  <span id={`${ids}-instrumental-${card.key}`}>Instrumental</span>
                  <Toggle
                    checked={card.instrumental}
                    labelledBy={`${ids}-instrumental-${card.key}`}
                    disabled={card.writing}
                    onChange={(instrumental) => update(card.key, { instrumental })}
                  />
                </div>
              </div>
            </article>
          ))}
        </>
      )}

      {step === "review" && (
        <>
          <p className={styles.intro}>
            Listen here, on this device. Kept ones join the {system ? "system" : "station"} idents
            straight away. Turned down ones are thrown out, and the AI remembers to steer clear of
            them.
          </p>
          {drafts.map((draft) => (
            <Draft
              key={draft.id}
              draft={draft}
              busy={busy === draft.id}
              name={names[draft.id] ?? draft.name}
              fix={fixes[draft.id] ?? draft.suggestion ?? draft.prompt}
              at={playing?.id === draft.id ? playing.at : null}
              onName={(name) => setNames((all) => ({ ...all, [draft.id]: name }))}
              onRename={() => rename(draft)}
              onFixText={(text) => setFixes((all) => ({ ...all, [draft.id]: text }))}
              onListen={() => listen(draft)}
              onDecide={(status) => decide(draft, status)}
              onAgain={() => again(draft)}
              onFix={() => fix(draft)}
              onLeaveOut={() => leaveOut(draft)}
            />
          ))}
        </>
      )}

      <FormError message={error} />
    </Dialog>
  );
}

type DraftProps = {
  draft: JingleDraft;
  busy: boolean;
  /** Its name as it's being typed. */
  name: string;
  /** A refused one's description, being changed. */
  fix: string;
  /** Seconds in, while it's playing here. */
  at: number | null;
  onName: (name: string) => void;
  onRename: () => void;
  onFixText: (text: string) => void;
  onListen: () => void;
  onDecide: (status: DraftStatus) => void;
  onAgain: () => void;
  onFix: () => void;
  onLeaveOut: () => void;
};

function Draft({ draft, busy, name, fix, at, ...on }: DraftProps) {
  const { status } = draft;
  const playing = at !== null;
  const seconds = draft.seconds ?? draft.length;

  if (status === "failed") {
    return (
      <article className={`${styles.draft} ${styles.failed}`}>
        <div className={styles.draftHead}>
          <span className={styles.alert}>
            <Icon name="alert" size={20} />
          </span>
          <div className={styles.draftText}>
            <span className={styles.draftName}>{draft.name}</span>
            <span className={styles.problem}>
              {draft.problem}
              {draft.suggestion && " ElevenLabs suggested the wording below instead."}
            </span>
          </div>
        </div>
        <textarea
          rows={2}
          maxLength={1000}
          value={fix}
          disabled={busy}
          aria-label={`Describe ${draft.name}`}
          className={styles.textarea}
          onChange={(event) => on.onFixText(event.target.value)}
        />
        <div className={styles.actions}>
          <Button variant="ghost" disabled={busy} onClick={on.onLeaveOut}>
            Leave it out
          </Button>
          <button type="button" className={styles.ai} disabled={busy} onClick={on.onFix}>
            <Icon name="sparkle" size={16} />
            Fix with AI
          </button>
          <Button variant="secondary" disabled={busy || !fix.trim()} onClick={on.onAgain}>
            <Icon name="again" size={15} strokeWidth={2.2} />
            Try again
          </Button>
        </div>
      </article>
    );
  }

  const making = status === "making";
  return (
    <article
      className={`${styles.draft} ${status === "kept" ? styles.kept : ""} ${status === "turned_down" ? styles.down : ""}`}
    >
      <div className={styles.draftHead}>
        <button
          type="button"
          className={`${styles.play} ${playing ? styles.on : ""}`}
          disabled={making || !draft.url}
          aria-label={making ? `Making ${draft.name}` : playing ? `Stop ${draft.name}` : `Play ${draft.name}`}
          onClick={on.onListen}
        >
          {making ? (
            <span className={styles.spin}>
              <Icon name="again" size={20} strokeWidth={2.4} />
            </span>
          ) : (
            <Icon name={playing ? "stop" : "play"} size={16} />
          )}
        </button>
        <div className={styles.draftText}>
          <input
            type="text"
            value={name}
            maxLength={100}
            disabled={status === "turned_down" || busy}
            aria-label="Jingle name"
            className={styles.name}
            onChange={(event) => on.onName(event.target.value)}
            onBlur={on.onRename}
            onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
          />
          {making ? (
            <div className={styles.progress}>
              <span className={styles.track}>
                <span className={styles.sweep} />
              </span>
              <span className={styles.status}>Composing...</span>
            </div>
          ) : (
            <div className={styles.progress}>
              <span className={styles.track}>
                <span className={styles.fill} style={{ width: `${playing ? Math.min(100, (at / seconds) * 100) : 0}%` }} />
              </span>
              <span className={styles.time}>
                {clock(at ?? 0)} / {clock(seconds)}
              </span>
            </div>
          )}
        </div>
        {status === "kept" && (
          <span className={styles.keptChip}>
            <Icon name="check" size={12} strokeWidth={3} />
            Kept
          </span>
        )}
        {status === "turned_down" && <span className={styles.downChip}>Turned down</span>}
      </div>
      <p className={styles.description}>
        {draft.instrumental ? "Instrumental. " : ""}
        {draft.length} seconds. {draft.prompt}
      </p>
      {draft.problem && status !== "turned_down" && (
        <p className={styles.note}>
          <Icon name="alert" size={16} />
          <span>{draft.problem}</span>
        </p>
      )}
      {status === "ready" && (
        <div className={styles.actions}>
          <Button variant="ghost" disabled={busy} onClick={() => on.onDecide("turned_down")}>
            Turn down
          </Button>
          <Button variant="secondary" disabled={busy} onClick={on.onAgain}>
            <Icon name="again" size={15} strokeWidth={2.2} />
            Try again
          </Button>
          <Button disabled={busy} onClick={() => on.onDecide("kept")} className={styles.keep}>
            <Icon name="check" size={15} strokeWidth={2.6} />
            Keep
          </Button>
        </div>
      )}
      {(status === "kept" || status === "turned_down") && (
        <div className={styles.actions}>
          <Button variant="ghost" disabled={busy} onClick={() => on.onDecide("ready")}>
            Undo
          </Button>
        </div>
      )}
    </article>
  );
}
