import type { AnnounceMode, Announcement, Day, Repeat } from "../api";

/** Monday first, as the day keys come from the server. */
export const DAYS: { day: Day; letter: string; short: string; long: string }[] = [
  { day: "mon", letter: "M", short: "Mon", long: "Monday" },
  { day: "tue", letter: "T", short: "Tue", long: "Tuesday" },
  { day: "wed", letter: "W", short: "Wed", long: "Wednesday" },
  { day: "thu", letter: "T", short: "Thu", long: "Thursday" },
  { day: "fri", letter: "F", short: "Fri", long: "Friday" },
  { day: "sat", letter: "S", short: "Sat", long: "Saturday" },
  { day: "sun", letter: "S", short: "Sun", long: "Sunday" },
];

export const REPEATS: { value: Repeat; label: string }[] = [
  { value: "once", label: "Just once" },
  { value: "daily", label: "Every day" },
  { value: "weekdays", label: "Weekdays" },
  { value: "days", label: "Chosen days" },
  { value: "hourly", label: "Every hour" },
];

export const HOW: Record<AnnounceMode, string> = {
  after: "After the current song",
  over: "Over the music",
};

/** "a, b and c". */
export function listed(items: string[]): string {
  return items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;
}

/** "Wed 14 Oct", from "2026-10-14". */
export function shortDate(iso: string): string {
  return new Date(`${iso}T12:00`).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function time(date: Date): string {
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** "today", "tomorrow", "yesterday", a weekday within the week, or a date. */
function dayWord(date: Date): string {
  const midnight = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((midnight(date) - midnight(new Date())) / 86_400_000);
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "yesterday";
  if (days > 1 && days < 7) return date.toLocaleDateString(undefined, { weekday: "long" });
  return date.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

const capitalise = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** The schedule, for a chip: "Weekdays 12:30", "Tue and Thu 09:00", "Wed 14 Oct 09:55". */
export function describeWhen(rule: Pick<Announcement, "repeat" | "days" | "at" | "start_date">) {
  switch (rule.repeat) {
    case "once":
      return `${shortDate(rule.start_date)} ${rule.at}`;
    case "daily":
      return `Every day ${rule.at}`;
    case "weekdays":
      return `Weekdays ${rule.at}`;
    case "hourly":
      return `Every hour at :${rule.at.slice(3)}`;
    case "days": {
      const chosen = DAYS.filter(({ day }) => rule.days.includes(day)).map(({ short }) => short);
      return `${listed(chosen)} ${rule.at}`;
    }
  }
}

/** "All rooms" or "Kitchen, Donut Shop". */
export function describeWhere(rooms: string[] | null): string {
  return rooms && rooms.length > 0 ? rooms.join(", ") : "All rooms";
}

/** "Next: today at 12:30". */
export function describeNext(rule: Announcement): string {
  if (!rule.next_at) return "Won't play again";
  const next = new Date(rule.next_at);
  return `Next: ${dayWord(next)} at ${time(next)}`;
}

/** When a log entry happened: "Today 12:31", "Monday 09:00". */
export function describePlayed(iso: string): string {
  const played = new Date(iso);
  return `${capitalise(dayWord(played))} ${time(played)}`;
}

type Plan = {
  rooms: string[];
  now: boolean;
  mode: AnnounceMode;
  start_date: string;
  at: string;
  repeat: Repeat;
  days: Day[];
  ends_on: string;
};

/** The whole plan in a sentence, for checking before it's saved. */
export function summarise(plan: Plan): string {
  const where = plan.rooms.length > 0 ? `in ${listed(plan.rooms)}` : "in all rooms";
  const how = plan.mode === "after" ? "after the current song" : "over the music";
  if (plan.now) return `Plays ${where} now, ${how}.`;
  if (!plan.start_date || !plan.at) return `Plays ${where}, ${how}, once you pick a time.`;

  const from = shortDate(plan.start_date);
  const chosen = DAYS.filter(({ day }) => plan.days.includes(day)).map(({ long }) => long);
  const when = {
    once: `on ${from} at ${plan.at}`,
    daily: `every day at ${plan.at} from ${from}`,
    weekdays: `on weekdays at ${plan.at} from ${from}`,
    days: `every ${chosen.length ? listed(chosen) : "chosen day"} at ${plan.at} from ${from}`,
    hourly: `every hour at :${plan.at.slice(3)} from ${plan.at} on ${from}, in playback hours`,
  }[plan.repeat];
  const until = plan.repeat !== "once" && plan.ends_on ? `, until ${shortDate(plan.ends_on)}` : "";
  return `Plays ${where} ${when}${until}, ${how}.`;
}
