import type { LineupDay, LineupSlot } from "../api";

/** Line-up slots start and end on the quarter hour. */
export const STEP = 15;

/** 510 to "08:30". */
export function clock(minute: number): string {
  const hours = Math.floor(minute / 60);
  return `${String(hours).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
}

/** 90 to "1 h 30", 45 to "45 min". */
export function length(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!hours) return `${rest} min`;
  return rest ? `${hours} h ${rest}` : `${hours} h`;
}

/** A stretch of the day: a slot, or a gap between slots when `slot` is null. */
export type Stretch = { start: number; end: number; slot: LineupSlot | null };

/** The day from opening to closing as slots and the gaps between them. */
export function stretches(slots: LineupSlot[], day: LineupDay): Stretch[] {
  const out: Stretch[] = [];
  let at = day.start;
  for (const slot of [...slots].sort((a, b) => a.start - b.start)) {
    if (slot.end <= day.start || slot.start >= day.end) continue;
    if (slot.start > at) out.push({ start: at, end: slot.start, slot: null });
    out.push({ start: Math.max(slot.start, day.start), end: Math.min(slot.end, day.end), slot });
    at = Math.min(slot.end, day.end);
  }
  if (at < day.end) out.push({ start: at, end: day.end, slot: null });
  return out;
}

/** "5 slots · 08:00 to 18:00". */
export function summary(slots: LineupSlot[]): string {
  if (slots.length === 0) return "Nothing planned yet";
  const first = Math.min(...slots.map((slot) => slot.start));
  const last = Math.max(...slots.map((slot) => slot.end));
  const count = `${slots.length} ${slots.length === 1 ? "slot" : "slots"}`;
  return `${count} · ${clock(first)} to ${clock(last)}`;
}
