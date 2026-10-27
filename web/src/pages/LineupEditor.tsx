import {
  type DragEvent,
  type FormEvent,
  type PointerEvent,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api, errorText, type Lineup, type LineupChoices, type LineupDay } from "../api";
import { Button, ButtonLink } from "../components/Button";
import { Dialog } from "../components/Dialog";
import { HelpLink } from "../components/HelpLink";
import { Icon } from "../components/Icon";
import { useLeaveGuard } from "../components/LeaveGuard";
import { LineupCover } from "../components/LineupCover";
import { SegmentedControl } from "../components/SegmentedControl";
import { FormError, TextField } from "../components/TextField";
import { useToast } from "../components/Toast";
import { useWide } from "../components/useWide";
import { clock, length, STEP } from "../lineups/time";
import e from "./LineupEditor.module.css";
import { Legend } from "./LineupsPage";
import styles from "./Page.module.css";

const BACK = "/lineups";
const SHOW_MINUTES = 60; // a show dropped on the day starts at an hour long

type Kind = "show" | "playlist";
/** A slot as the editor has it. `key` tells slots apart while editing; `ref` is the station's
 * or playlist's id. */
type Draft = { key: number; kind: Kind; ref: number; start: number; end: number };
type Form = { name: string; description: string; slots: Draft[] };
type Spot = { start: number; end: number };

function byStart(slots: Draft[]): Draft[] {
  return [...slots].sort((a, b) => a.start - b.start);
}

/** What the form would save, to tell whether anything changed. */
function fingerprint(form: Form): string {
  const slots = byStart(form.slots).map(({ kind, ref, start, end }) => [kind, ref, start, end]);
  return JSON.stringify([form.name.trim(), form.description.trim(), slots]);
}

function snap(minute: number, day: LineupDay): number {
  return Math.min(day.end, Math.max(day.start, Math.round(minute / STEP) * STEP));
}

/** The free stretch around `minute`, leaving out the slot with `key`. */
function room(slots: Draft[], key: number | null, minute: number, day: LineupDay) {
  const others = byStart(slots.filter((slot) => slot.key !== key));
  const before = others.filter((slot) => slot.end <= minute);
  const after = others.filter((slot) => slot.start > minute);
  return {
    floor: before.length ? before[before.length - 1].end : day.start,
    ceiling: after.length ? after[0].start : day.end,
  };
}

/** The longest a slot can run: a playlist's own length, to the quarter hour, a show any length. */
function longest(kind: Kind, ref: number, choices: LineupChoices): number {
  if (kind === "show") return choices.day.end - choices.day.start;
  const minutes = choices.playlists.find((playlist) => playlist.id === ref)?.minutes ?? 0;
  return Math.floor(minutes / STEP) * STEP;
}

/** Where something put at `minute` would go: from there to the next slot, or as long as it
 * wants to be, whichever is shorter. Null when there's no room. */
function fit(kind: Kind, ref: number, minute: number, slots: Draft[], choices: LineupChoices): Spot | null {
  const start = Math.floor(minute / STEP) * STEP;
  if (start < choices.day.start || start >= choices.day.end) return null;
  if (slots.some((slot) => start >= slot.start && start < slot.end)) return null;
  const { ceiling } = room(slots, null, start, choices.day);
  const want = kind === "show" ? SHOW_MINUTES : longest(kind, ref, choices);
  const end = Math.floor(Math.min(start + want, ceiling) / STEP) * STEP;
  return end - start >= STEP ? { start, end } : null;
}

function firstGap(slots: Draft[], day: LineupDay): number | null {
  let at = day.start;
  for (const slot of [...byStart(slots), { start: day.end, end: day.end }]) {
    if (slot.start - at >= STEP) return at;
    at = Math.max(at, slot.end);
  }
  return null;
}

function gaps(slots: Draft[], day: LineupDay): Spot[] {
  const out: Spot[] = [];
  let at = day.start;
  for (const slot of [...byStart(slots), { start: day.end, end: day.end }]) {
    if (slot.start > at) out.push({ start: at, end: slot.start });
    at = Math.max(at, slot.end);
  }
  return out;
}

/** What a slot plays, as the choices name it. */
function about(draft: Draft, choices: LineupChoices) {
  if (draft.kind === "show") {
    const show = choices.shows.find((s) => s.id === draft.ref);
    return { name: show?.name ?? "A station", dj: show?.dj_name ?? null, minutes: null };
  }
  const playlist = choices.playlists.find((p) => p.id === draft.ref);
  return { name: playlist?.name ?? "A playlist", dj: null, minutes: playlist?.minutes ?? null };
}

/** What happens at a slot's edges: the hand-over for a show, the cut-off for a playlist. */
function slotNote(draft: Draft, choices: LineupChoices): string {
  const { dj, minutes } = about(draft, choices);
  if (draft.kind === "show") {
    return dj
      ? `Hand-over: it opens with its station ident, then ${dj} says what's on until ${clock(draft.end)}.`
      : "Hand-over: it opens with its station ident. It has no DJ, so nobody introduces it.";
  }
  return `Plays ${length(draft.end - draft.start)} of its ${length(minutes ?? 0)}. If it hasn't finished by ${clock(draft.end)}, it's cut off there.`;
}

function slotKind(draft: Draft, choices: LineupChoices): string {
  const { dj, minutes } = about(draft, choices);
  const runs = length(draft.end - draft.start);
  return draft.kind === "show"
    ? `Show · ${dj ? `DJ ${dj}` : "no DJ"} · ${runs}`
    : `Playlist · ${runs} of ${length(minutes ?? 0)}`;
}

function times(day: LineupDay): number[] {
  const out = [];
  for (let minute = day.start; minute <= day.end; minute += STEP) out.push(minute);
  return out;
}

/** The line-up editor: name, description and cover, and the day itself. */
export function LineupEditor() {
  const { id } = useParams();
  const editing = id !== undefined;
  const wide = useWide();
  const navigate = useNavigate();
  const { show, toast } = useToast();
  const [choices, setChoices] = useState<LineupChoices | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [saved, setSaved] = useState("");
  const [art, setArt] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [adding, setAdding] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const keys = useRef(1);

  useEffect(() => {
    Promise.all([
      api<LineupChoices>("GET", "/lineups/choices"),
      editing ? api<Lineup>("GET", `/lineups/${id}`) : Promise.resolve(null),
    ])
      .then(([offered, lineup]) => {
        const loaded: Form = {
          name: lineup?.name ?? "",
          description: lineup?.description ?? "",
          slots: (lineup?.slots ?? []).map((slot) => ({
            key: keys.current++,
            kind: slot.kind,
            ref: (slot.kind === "show" ? slot.station_id : slot.playlist_id) ?? 0,
            start: slot.start,
            end: slot.end,
          })),
        };
        setChoices(offered);
        setForm(loaded);
        setSaved(fingerprint(loaded));
        setArt(lineup?.art_url ?? null);
      })
      .catch((caught) => setError(errorText(caught)));
  }, [editing, id]);

  const dirty = !!form && fingerprint(form) !== saved;
  const { allow, dialog: leaving } = useLeaveGuard(dirty);

  const setSlots = (change: (slots: Draft[]) => Draft[]) =>
    setForm((current) => current && { ...current, slots: change(current.slots) });

  const place = (kind: Kind, ref: number, spot: Spot) => {
    const key = keys.current++;
    setSlots((slots) => [...slots, { key, kind, ref, ...spot }]);
    setSelected(key);
  };

  const addToFirstGap = (kind: Kind, ref: number) => {
    if (!form || !choices) return;
    const at = firstGap(form.slots, choices.day);
    const spot = at === null ? null : fit(kind, ref, at, form.slots, choices);
    if (spot) place(kind, ref, spot);
    else show("The day is full. Shorten a slot to make room.");
  };

  /** A new start or end from the times, kept clear of its neighbours and its length. */
  const setTime = (key: number, which: "start" | "end", minute: number) => {
    if (!form || !choices) return;
    const slot = form.slots.find((s) => s.key === key);
    if (!slot) return;
    const { floor, ceiling } = room(form.slots, key, slot.start, choices.day);
    const most = longest(slot.kind, slot.ref, choices);
    const value =
      which === "start"
        ? Math.min(Math.max(minute, floor, slot.end - most), slot.end - STEP)
        : Math.max(Math.min(minute, ceiling, slot.start + most), slot.start + STEP);
    if (value !== minute) {
      show(`That would overlap or stretch it, so it ${which === "start" ? "starts" : "ends"} at ${clock(value)}.`);
    }
    setSlots((slots) => slots.map((s) => (s.key === key ? { ...s, [which]: value } : s)));
  };

  const remove = (key: number) => {
    setSlots((slots) => slots.filter((slot) => slot.key !== key));
    setSelected(null);
  };

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!form) return;
    setBusy(true);
    setError(null);
    const body = {
      name: form.name,
      description: form.description,
      slots: byStart(form.slots).map((slot) => ({
        start: slot.start,
        end: slot.end,
        [slot.kind === "show" ? "station_id" : "playlist_id"]: slot.ref,
      })),
    };
    try {
      const done = await api<Lineup>(editing ? "PUT" : "POST", editing ? `/lineups/${id}` : "/lineups", body);
      allow();
      navigate(BACK, { state: { said: editing ? "Saved." : `${done.name} is ready to put on.` } });
    } catch (caught) {
      setError(errorText(caught));
      setBusy(false);
    }
  };

  const destroy = async () => {
    try {
      await api("DELETE", `/lineups/${id}`);
      allow();
      navigate(BACK, { state: { said: "Deleted." } });
    } catch (caught) {
      setDeleting(false);
      setError(errorText(caught));
    }
  };

  const chosen = form?.slots.find((slot) => slot.key === selected) ?? null;
  const ready = !!form && !!form.name.trim();

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerStart}>
          <Link to={BACK} aria-label="Back to Line-ups" className={styles.iconLink}>
            <Icon name="back" />
          </Link>
          <h1 className={styles.title}>{editing ? form?.name || "Line-up" : "New line-up"}</h1>
        </div>
        <div className={styles.headerEnd}>
          <span className={e.saveState}>{dirty ? "Unsaved changes" : editing ? "Saved" : ""}</span>
          <HelpLink />
        </div>
      </header>

      {!form && <FormError message={error} />}
      {form && choices && (
        <form className={e.form} onSubmit={submit}>
          <div className={e.about}>
            <div className={e.fields}>
              <TextField
                label="Name"
                value={form.name}
                maxLength={100}
                placeholder="Office Day"
                onChange={(event) => setForm({ ...form, name: event.target.value })}
              />
              <Description
                value={form.description}
                onChange={(description) => setForm({ ...form, description })}
              />
            </div>
            {editing ? (
              <Cover
                lineupId={Number(id)}
                url={art}
                name={form.name.trim()}
                description={form.description.trim()}
                onPainted={setArt}
                onError={setError}
              />
            ) : (
              <p className={`${styles.muted} ${e.coverNote}`}>
                Once it's created, OpenAI paints its cover from the name and description.
              </p>
            )}
          </div>

          <section className={e.day} aria-labelledby="day">
            <div className={e.dayTop}>
              <h2 id="day" className={styles.sectionTitle}>
                The day
              </h2>
              {!wide && (
                <Button
                  variant="secondary"
                  onClick={() => {
                    const at = firstGap(form.slots, choices.day);
                    if (at === null) show("The day is full. Shorten a slot to make room.");
                    else setAdding(newDraft(choices, form.slots, at, keys.current));
                  }}
                >
                  <Icon name="plus" size={16} strokeWidth={2.6} />
                  Add
                </Button>
              )}
            </div>
            <p className={styles.muted}>
              {wide
                ? "Drag a show or a playlist onto the day. Drag a slot to move it, or pull its ends to change its times. Everything snaps to 15 minutes."
                : "Tap a slot to change its times, or a gap to put something in it. Times go in 15-minute steps."}
            </p>
            {wide ? (
              <DayBar
                form={form}
                choices={choices}
                selected={selected}
                onSelect={setSelected}
                onSlots={setSlots}
                onPlace={place}
                onFull={() => show("No room there. Drop it on a gap.")}
              />
            ) : (
              <DayColumn
                form={form}
                choices={choices}
                onPick={setSelected}
                onGap={(at) => setAdding(newDraft(choices, form.slots, at, keys.current))}
              />
            )}
            <Legend />
            <p className={e.note}>
              Requests always play first, so the timings can shift a little: each slot starts at
              the first song change after its time, up to a song late, and the day never drifts.
              On a day with shorter playback hours, the slots outside them don't play.
            </p>
          </section>

          {wide && (
            <div className={e.lower}>
              <Palette choices={choices} onAdd={addToFirstGap} />
              <section className={e.panel} aria-labelledby="slot">
                <h2 id="slot" className={styles.sectionTitle}>
                  {chosen ? about(chosen, choices).name : "Slot"}
                </h2>
                {chosen ? (
                  <SlotFields
                    draft={chosen}
                    choices={choices}
                    onTime={(which, minute) => setTime(chosen.key, which, minute)}
                    onRemove={() => remove(chosen.key)}
                  />
                ) : (
                  <p className={styles.muted}>Pick a slot on the day to change its times or take it off.</p>
                )}
              </section>
            </div>
          )}

          <FormError message={error} />
          <div className={e.actions}>
            {editing && (
              <Button variant="ghost" onClick={() => setDeleting(true)}>
                Delete line-up
              </Button>
            )}
            <span className={e.spacer} />
            <ButtonLink variant="secondary" to={BACK}>
              Cancel
            </ButtonLink>
            <Button type="submit" disabled={busy || !ready}>
              {editing ? "Save" : "Create line-up"}
            </Button>
          </div>
        </form>
      )}

      {form && choices && !wide && (
        <>
          <Dialog
            open={chosen !== null && adding === null}
            onClose={() => setSelected(null)}
            title={chosen ? about(chosen, choices).name : ""}
          >
            {chosen && (
              <SlotFields
                draft={chosen}
                choices={choices}
                onTime={(which, minute) => setTime(chosen.key, which, minute)}
                onRemove={() => remove(chosen.key)}
                onDone={() => setSelected(null)}
              />
            )}
          </Dialog>
          <Dialog open={adding !== null} onClose={() => setAdding(null)} title="Add to the day">
            {adding && (
              <AddFields
                draft={adding}
                choices={choices}
                slots={form.slots}
                onChange={setAdding}
                onCancel={() => setAdding(null)}
                onAdd={(draft) => {
                  place(draft.kind, draft.ref, { start: draft.start, end: draft.end });
                  setAdding(null);
                  setSelected(null);
                  show(`${about(draft, choices).name} added, ${clock(draft.start)} to ${clock(draft.end)}.`);
                }}
                onRefused={show}
              />
            )}
          </Dialog>
        </>
      )}

      {leaving}
      <Dialog open={deleting} onClose={() => setDeleting(false)} title="Delete this line-up?">
        <p className={styles.muted}>
          If it's on, nothing fills the gaps between requests until the queue runs out.
        </p>
        <div className={e.dialogActions}>
          <Button variant="secondary" block onClick={() => setDeleting(false)}>
            Keep it
          </Button>
          <Button block onClick={destroy}>
            Delete
          </Button>
        </div>
      </Dialog>
      {toast}
    </div>
  );
}

/** A draft for the Add sheet: the first show, from `at`, as long as there's room for. */
function newDraft(choices: LineupChoices, slots: Draft[], at: number, key: number): Draft | null {
  const kind: Kind = choices.shows.length ? "show" : "playlist";
  const ref = (kind === "show" ? choices.shows[0]?.id : choices.playlists[0]?.id) ?? 0;
  const spot = fit(kind, ref, at, slots, choices);
  return spot ? { key, kind, ref, ...spot } : null;
}

function Description({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const id = useId();
  return (
    <div className={e.field}>
      <label htmlFor={id} className={e.label}>
        Description
      </label>
      <textarea
        id={id}
        rows={3}
        maxLength={600}
        value={value}
        placeholder="A normal day: an easy start, DJs through to lunch, quieter afternoons."
        onChange={(event) => onChange(event.target.value)}
        className={e.textarea}
      />
    </div>
  );
}

type CoverProps = {
  lineupId: number;
  url: string | null;
  name: string;
  description: string;
  onPainted: (url: string | null) => void;
  onError: (message: string | null) => void;
};

/** The line-up's cover, and a button for another, painted from the form as it is. */
function Cover({ lineupId, url, name, description, onPainted, onError }: CoverProps) {
  const [busy, setBusy] = useState(false);
  const repaint = async () => {
    setBusy(true);
    onError(null);
    try {
      const lineup = await api<Lineup>("POST", `/lineups/${lineupId}/cover`, { name, description });
      onPainted(lineup.art_url);
    } catch (caught) {
      onError(errorText(caught));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={e.cover}>
      <LineupCover url={url} className={e.coverArt} iconSize={34} />
      <div className={e.coverText}>
        <span className={e.hint}>OpenAI paints the cover from the name and description.</span>
        <Button variant="secondary" disabled={busy || !name} onClick={repaint}>
          {busy ? "Painting, about half a minute..." : url ? "Paint another" : "Paint one"}
        </Button>
      </div>
    </div>
  );
}

type DayBarProps = {
  form: Form;
  choices: LineupChoices;
  selected: number | null;
  onSelect: (key: number | null) => void;
  onSlots: (change: (slots: Draft[]) => Draft[]) => void;
  onPlace: (kind: Kind, ref: number, spot: Spot) => void;
  onFull: () => void;
};

type Drag = { key: number; mode: "move" | "start" | "end"; rect: DOMRect; grab: number };

/** The desktop day: a bar from opening to closing, slots dragged on, moved and resized. */
function DayBar({ form, choices, selected, onSelect, onSlots, onPlace, onFull }: DayBarProps) {
  const { day } = choices;
  const span = day.end - day.start;
  const bar = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const [ghost, setGhost] = useState<Spot | null>(null);
  const pct = (minute: number) => ((minute - day.start) / span) * 100;
  const minuteAt = (clientX: number, rect: DOMRect) => day.start + ((clientX - rect.left) / rect.width) * span;

  const grab = (event: PointerEvent, key: number, mode: Drag["mode"]) => {
    event.stopPropagation();
    event.preventDefault();
    const rect = bar.current?.getBoundingClientRect();
    const slot = form.slots.find((s) => s.key === key);
    if (!rect || !slot) return;
    (event.currentTarget as Element).setPointerCapture(event.pointerId);
    drag.current = { key, mode, rect, grab: minuteAt(event.clientX, rect) - slot.start };
    onSelect(key);
  };

  const move = (event: PointerEvent) => {
    const held = drag.current;
    if (!held) return;
    const slot = form.slots.find((s) => s.key === held.key);
    if (!slot) return;
    const { floor, ceiling } = room(form.slots, slot.key, slot.start, day);
    const minute = minuteAt(event.clientX, held.rect);
    const most = longest(slot.kind, slot.ref, choices);
    let next: Spot = slot;
    if (held.mode === "move") {
      const runs = slot.end - slot.start;
      const start = Math.min(Math.max(snap(minute - held.grab, day), floor), ceiling - runs);
      if (start >= floor) next = { start, end: start + runs };
    } else if (held.mode === "start") {
      next = { ...slot, start: Math.min(Math.max(snap(minute, day), floor, slot.end - most), slot.end - STEP) };
    } else {
      next = { ...slot, end: Math.max(Math.min(snap(minute, day), ceiling, slot.start + most), slot.start + STEP) };
    }
    if (next.start !== slot.start || next.end !== slot.end) {
      onSlots((slots) => slots.map((s) => (s.key === slot.key ? { ...s, start: next.start, end: next.end } : s)));
    }
  };

  const carried = (event: DragEvent) => {
    const data = event.dataTransfer.getData("text/plain") || carrying.value;
    const [kind, ref] = data.split(":");
    return kind === "show" || kind === "playlist" ? { kind: kind as Kind, ref: Number(ref) } : null;
  };

  const spotFor = (event: DragEvent) => {
    const item = carried(event);
    const rect = bar.current?.getBoundingClientRect();
    if (!item || !rect) return null;
    return { item, spot: fit(item.kind, item.ref, minuteAt(event.clientX, rect), form.slots, choices) };
  };

  const hours = [];
  for (let hour = Math.ceil(day.start / 60) * 60; hour <= day.end; hour += 60) hours.push(hour);

  return (
    <div className={e.barWrap}>
      <div className={e.hours}>
        {hours.map((hour) => (
          <span
            key={hour}
            className={e.hour}
            style={{
              left: `${pct(hour)}%`,
              transform: hour === day.start ? "none" : hour === day.end ? "translateX(-100%)" : undefined,
            }}
          >
            {clock(hour)}
          </span>
        ))}
      </div>
      <div
        ref={bar}
        className={e.bar}
        style={{ backgroundSize: `${(60 / span) * 100}% 100%, ${(STEP / span) * 100}% 100%` }}
        onPointerMove={move}
        onPointerUp={() => (drag.current = null)}
        onPointerCancel={() => (drag.current = null)}
        onDragOver={(event) => {
          event.preventDefault();
          const found = spotFor(event);
          const spot = found?.spot ?? null;
          if (spot?.start !== ghost?.start || spot?.end !== ghost?.end) setGhost(spot);
        }}
        onDragLeave={() => setGhost(null)}
        onDrop={(event) => {
          event.preventDefault();
          setGhost(null);
          const found = spotFor(event);
          if (found?.spot) onPlace(found.item.kind, found.item.ref, found.spot);
          else onFull();
        }}
      >
        {gaps(form.slots, day).map((gap) => (
          <span
            key={gap.start}
            className={e.gap}
            style={{ left: `calc(${pct(gap.start)}% + 2px)`, width: `calc(${pct(gap.end) - pct(gap.start)}% - 4px)` }}
          >
            {gap.end - gap.start >= 30 ? "Gap" : ""}
          </span>
        ))}
        {byStart(form.slots).map((slot) => {
          const { name } = about(slot, choices);
          const isSelected = slot.key === selected;
          return (
            <div
              key={slot.key}
              role="button"
              tabIndex={0}
              aria-pressed={isSelected}
              aria-label={`${name}, ${clock(slot.start)} to ${clock(slot.end)}`}
              className={`${e.slot} ${e[slot.kind]} ${isSelected ? e.selected : ""}`}
              style={{ left: `calc(${pct(slot.start)}% + 2px)`, width: `calc(${pct(slot.end) - pct(slot.start)}% - 4px)` }}
              onPointerDown={(event) => grab(event, slot.key, "move")}
              onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && onSelect(slot.key)}
            >
              <span className={e.slotName}>
                <Icon name={slot.kind === "show" ? "radio" : "library"} size={14} />
                {name}
              </span>
              <span className={e.slotTimes}>
                {clock(slot.start)} to {clock(slot.end)}
              </span>
              {isSelected && (
                <>
                  <span aria-hidden="true" className={`${e.handle} ${e.handleStart}`} onPointerDown={(event) => grab(event, slot.key, "start")} />
                  <span aria-hidden="true" className={`${e.handle} ${e.handleEnd}`} onPointerDown={(event) => grab(event, slot.key, "end")} />
                </>
              )}
            </div>
          );
        })}
        {ghost && (
          <span
            className={e.ghost}
            style={{ left: `${pct(ghost.start)}%`, width: `${pct(ghost.end) - pct(ghost.start)}%` }}
          >
            {clock(ghost.start)} to {clock(ghost.end)}
          </span>
        )}
      </div>
    </div>
  );
}

// Browsers only let a drop see what's carried, not a drag-over, so it's kept here too.
const carrying = { value: "" };

/** The shows and playlists to drag onto the day, or click to put in the first gap. */
function Palette({ choices, onAdd }: { choices: LineupChoices; onAdd: (kind: Kind, ref: number) => void }) {
  const chip = (kind: Kind, ref: number, name: string, meta: string, art: string | null) => (
    <button
      key={`${kind}${ref}`}
      type="button"
      draggable
      className={e.chip}
      onDragStart={(event) => {
        carrying.value = `${kind}:${ref}`;
        event.dataTransfer.setData("text/plain", carrying.value);
        event.dataTransfer.effectAllowed = "copy";
      }}
      onDragEnd={() => (carrying.value = "")}
      onClick={() => onAdd(kind, ref)}
    >
      {art ? (
        <img src={art} alt="" className={e.chipArt} />
      ) : (
        <span aria-hidden="true" className={e.chipArt}>
          <Icon name={kind === "show" ? "radio" : "library"} size={14} />
        </span>
      )}
      <span className={e.chipText}>
        <span className={e.chipName}>{name}</span>
        <span className={e.chipMeta}>{meta}</span>
      </span>
    </button>
  );
  return (
    <section className={e.panel} aria-labelledby="add">
      <h2 id="add" className={styles.sectionTitle}>
        Add to the day
      </h2>
      <p className={styles.muted}>
        Drag one onto the day, or click it to put it in the first gap. A show starts at an hour; a
        playlist at its own length, which can be shortened but not stretched.
      </p>
      <span className={e.group}>Shows</span>
      <div className={e.chips}>
        {choices.shows.map((show) => chip("show", show.id, show.name, show.dj_name ? `DJ ${show.dj_name}` : "No DJ", show.art_url))}
      </div>
      <span className={e.group}>Playlists</span>
      <div className={e.chips}>
        {choices.playlists.map((playlist) =>
          chip("playlist", playlist.id, playlist.name, length(playlist.minutes), playlist.covers[0] ?? null),
        )}
        {choices.playlists.length === 0 && <p className={styles.muted}>No playlists long enough yet.</p>}
      </div>
    </section>
  );
}

const PX_PHONE = 1; // a pixel a minute down the phone's day

/** The phone day: running down the screen like a calendar, gaps to tap to add something. */
function DayColumn({
  form,
  choices,
  onPick,
  onGap,
}: {
  form: Form;
  choices: LineupChoices;
  onPick: (key: number) => void;
  onGap: (at: number) => void;
}) {
  const { day } = choices;
  const top = (minute: number) => (minute - day.start) * PX_PHONE;
  const hours = [];
  for (let hour = Math.ceil(day.start / 60) * 60; hour <= day.end; hour += 60) hours.push(hour);
  return (
    <div className={e.column} style={{ height: top(day.end) + 8 }}>
      {hours.map((hour) => (
        <span key={hour}>
          <span className={e.columnHour} style={{ top: top(hour) }}>
            {clock(hour)}
          </span>
          <span aria-hidden="true" className={e.columnLine} style={{ top: top(hour) }} />
        </span>
      ))}
      {gaps(form.slots, day).map((gap) => (
        <button
          key={gap.start}
          type="button"
          className={e.columnGap}
          style={{ top: top(gap.start) + 2, height: (gap.end - gap.start) * PX_PHONE - 4 }}
          onClick={() => onGap(gap.start)}
        >
          {gap.end - gap.start >= 30 ? `+ Add ${clock(gap.start)} to ${clock(gap.end)}` : "+"}
        </button>
      ))}
      {byStart(form.slots).map((slot) => {
        const tall = slot.end - slot.start >= 45;
        return (
          <button
            key={slot.key}
            type="button"
            className={`${e.columnSlot} ${e[slot.kind]} ${tall ? e.tall : ""}`}
            style={{ top: top(slot.start) + 2, height: (slot.end - slot.start) * PX_PHONE - 4 }}
            onClick={() => onPick(slot.key)}
          >
            <span className={e.slotName}>{about(slot, choices).name}</span>
            <span className={e.slotTimes}>
              {clock(slot.start)} to {clock(slot.end)}
            </span>
          </button>
        );
      })}
    </div>
  );
}

type SlotFieldsProps = {
  draft: Draft;
  choices: LineupChoices;
  onTime: (which: "start" | "end", minute: number) => void;
  onRemove: () => void;
  onDone?: () => void;
};

/** A slot's times, what happens at its edges, and taking it off. */
function SlotFields({ draft, choices, onTime, onRemove, onDone }: SlotFieldsProps) {
  return (
    <div className={e.slotFields}>
      <span className={e.hint}>{slotKind(draft, choices)}</span>
      <Times draft={draft} day={choices.day} onTime={onTime} />
      <p className={e.slotNote}>{slotNote(draft, choices)}</p>
      <div className={e.dialogActions}>
        <Button variant="secondary" onClick={onRemove}>
          Take off the day
        </Button>
        {onDone && <Button onClick={onDone}>Done</Button>}
      </div>
    </div>
  );
}

function Times({
  draft,
  day,
  onTime,
}: {
  draft: Spot;
  day: LineupDay;
  onTime: (which: "start" | "end", minute: number) => void;
}) {
  const startId = useId();
  const endId = useId();
  const options = times(day);
  return (
    <div className={e.times}>
      <div className={e.field}>
        <label htmlFor={startId} className={e.label}>
          Starts
        </label>
        <select
          id={startId}
          className={e.select}
          value={draft.start}
          onChange={(event) => onTime("start", Number(event.target.value))}
        >
          {options.map((minute) => (
            <option key={minute} value={minute}>
              {clock(minute)}
            </option>
          ))}
        </select>
      </div>
      <div className={e.field}>
        <label htmlFor={endId} className={e.label}>
          Ends
        </label>
        <select
          id={endId}
          className={e.select}
          value={draft.end}
          onChange={(event) => onTime("end", Number(event.target.value))}
        >
          {options.map((minute) => (
            <option key={minute} value={minute}>
              {clock(minute)}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

type AddFieldsProps = {
  draft: Draft;
  choices: LineupChoices;
  slots: Draft[];
  onChange: (draft: Draft) => void;
  onCancel: () => void;
  onAdd: (draft: Draft) => void;
  onRefused: (message: string) => void;
};

/** The phone's Add sheet: a show or a playlist, which one, and when. */
function AddFields({ draft, choices, slots, onChange, onCancel, onAdd, onRefused }: AddFieldsProps) {
  const whichId = useId();
  const options = draft.kind === "show" ? choices.shows : choices.playlists;

  const retarget = (kind: Kind, ref: number) => {
    const spot = fit(kind, ref, draft.start, slots, choices);
    onChange({ ...draft, kind, ref, ...(spot ?? { end: draft.start + STEP }) });
  };

  const setTime = (which: "start" | "end", minute: number) => {
    if (which === "start") {
      const spot = fit(draft.kind, draft.ref, minute, slots, choices);
      if (!spot) {
        onRefused(`Something is already on at ${clock(minute)}.`);
        return;
      }
      onChange({ ...draft, start: spot.start, end: Math.min(spot.start + (draft.end - draft.start), spot.end) });
      return;
    }
    const { ceiling } = room(slots, null, draft.start, choices.day);
    const end = Math.max(
      Math.min(minute, ceiling, draft.start + longest(draft.kind, draft.ref, choices)),
      draft.start + STEP,
    );
    if (end !== minute) onRefused(`That would overlap or stretch it, so it ends at ${clock(end)}.`);
    onChange({ ...draft, end });
  };

  return (
    <div className={e.slotFields}>
      <SegmentedControl
        label="What to add"
        value={draft.kind}
        onChange={(kind) => {
          const first = kind === "show" ? choices.shows[0] : choices.playlists[0];
          if (first) retarget(kind, first.id);
        }}
        options={[
          { value: "show" as const, label: "A show" },
          { value: "playlist" as const, label: "A playlist" },
        ]}
      />
      <div className={e.field}>
        <label htmlFor={whichId} className={e.label}>
          {draft.kind === "show" ? "Which show" : "Which playlist"}
        </label>
        <select
          id={whichId}
          className={e.select}
          value={draft.ref}
          onChange={(event) => retarget(draft.kind, Number(event.target.value))}
        >
          {options.map((option) => (
            <option key={option.id} value={option.id}>
              {option.name}
              {"minutes" in option ? ` · ${length(option.minutes)}` : option.dj_name ? ` · DJ ${option.dj_name}` : " · no DJ"}
            </option>
          ))}
        </select>
      </div>
      <Times draft={draft} day={choices.day} onTime={setTime} />
      <p className={e.slotNote}>{slotNote(draft, choices)}</p>
      <div className={e.dialogActions}>
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button onClick={() => onAdd(draft)}>Add</Button>
      </div>
    </div>
  );
}
