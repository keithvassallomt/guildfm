import type { DJProfile, StationDJ, StationFields, Voices } from "../api";
import { isEleven } from "../components/useVoices";
import { listed } from "../pages/announcementText";

/** What kind of station it is. Not stored: read from its DJs and its Talk Station switch, and
 * saved as them. */
export type Kind = "music" | "dj" | "talk";

/** A part of a station, as a step of the wizard and as a Change on the station's page. */
export type Step = "type" | "music" | "djs" | "talking" | "show" | "extras";

export const KINDS: { kind: Kind; title: string; text: string; cost: string }[] = [
  {
    kind: "music",
    title: "Just music",
    text: "Songs the AI picks from your description, with jingles if you like. Nobody talks.",
    cost: "No voice credits",
  },
  {
    kind: "dj",
    title: "Music with a DJ",
    text: "One DJ introduces the songs, shouts out requests and chats now and then.",
    cost: "About 90 credits a line",
  },
  {
    kind: "talk",
    title: "Talk show",
    text: "Two or more DJs chat, bicker and banter, with songs in between.",
    cost: "5,400 to 27,000 credits an hour",
  },
];

export const kindTitle = (kind: Kind) => KINDS.find((k) => k.kind === kind)?.title ?? "";

/** As many DJs as a station can have (MOST_DJS in api/stations.py). */
export const MOST_DJS = 6;

/** A station as it's being made or changed: its fields, and the kind picked for it. */
export type Draft = StationFields & {
  kind: Kind | null;
  /** New DJs made here who aren't on it just now, so taking one off doesn't lose them. */
  spare: StationDJ[];
};

export const BLANK: StationFields = {
  name: "",
  description: "",
  global_awareness: true,
  dj: false,
  dj_id: null,
  dj_name: "",
  personality: "",
  voice: "marin",
  talk_every: 3,
  talk_unit: "tracks",
  style: "commentary",
  announce_requests: true,
  jingles: true,
  crossfade: false,
  djs: [],
  dynamic: "",
  talk_station: false,
  talk_ratio: 45,
  script_prompt: "",
};

export const blankDraft = (): Draft => ({ ...BLANK, kind: null, spare: [] });

/** A station's own fields, as the API takes them back. */
export function fieldsOf(station: StationFields): StationFields {
  const fields = { ...BLANK };
  for (const key of Object.keys(BLANK) as (keyof StationFields)[]) {
    (fields as Record<string, unknown>)[key] = station[key];
  }
  return fields;
}

/** What kind a saved station is. One with two or more DJs that isn't a talk station shows as
 * Music with a DJ: only its first DJ talks. */
export function kindOf(station: StationFields): Kind {
  if (!station.dj || station.djs.length === 0) return "music";
  return station.talk_station ? "talk" : "dj";
}

export const draftOf = (station: StationFields): Draft => ({
  ...fieldsOf(station),
  kind: kindOf(station),
  spare: [],
});

/** The DJs on it, for its kind: none, the first, or all of them. */
export function hostsOf(draft: Draft): StationDJ[] {
  if (draft.kind === "music" || draft.kind === null) return [];
  return draft.kind === "dj" ? draft.djs.slice(0, 1) : draft.djs;
}

/** The draft as the API takes it. A station with a DJ keeps only its first unless `keepAll`,
 * for a station that has more and whose DJ hasn't been changed. */
export function sent(draft: Draft, keepAll = false): StationFields {
  const djs = draft.kind === "dj" && keepAll ? draft.djs : hostsOf(draft);
  const first = djs[0];
  return {
    ...fieldsOf(draft),
    djs,
    dj: djs.length > 0,
    dj_id: first?.id ?? null,
    dj_name: first?.name ?? "",
    personality: first?.personality ?? "",
    voice: first?.voice ?? "marin",
    talk_station: draft.kind === "talk",
  };
}

/** The steps a kind needs, in order, before the wizard's review. Until a kind is picked, the
 * ones for a station with a DJ. */
export function stepsFor(kind: Kind | null): Step[] {
  if (kind === "music") return ["type", "music", "extras"];
  if (kind === "talk") return ["type", "music", "djs", "show", "extras"];
  return ["type", "music", "djs", "talking", "extras"];
}

/** A step's name: in the wizard's stepper, and as the title of its Change. */
export function stepTitle(step: Step, kind: Kind | null): string {
  switch (step) {
    case "type":
      return "Type";
    case "music":
      return "Name and music";
    case "djs":
      return kind === "talk" ? "Hosts" : "DJ";
    case "talking":
      return "Talking";
    case "show":
      return "The show";
    case "extras":
      return "Extras";
  }
}

/** A step's short name, in the wizard's stepper. */
export const stepLabel = (step: Step | "review", kind: Kind | null) =>
  step === "review" ? "Review" : step === "music" ? "Music" : stepTitle(step, kind);

/** The question a step asks, over it in the wizard. */
export function question(step: Step | "review", draft: Draft): string {
  const talk = draft.kind === "talk";
  switch (step) {
    case "type":
      return "What kind of station?";
    case "music":
      return talk ? "Name the show, and its music" : "Name it, and say what it plays";
    case "djs":
      return talk ? "Who's on the show?" : "Who's the DJ?";
    case "talking":
      return `How should ${draft.djs[0]?.name.trim() || "the DJ"} talk?`;
    case "show":
      return "Shape the show";
    case "extras":
      return "Finishing touches";
    case "review":
      return "Ready to go?";
  }
}

/** A line under the step's question, or at the top of its Change. */
export function lead(step: Step | "review", draft: Draft, made: boolean): string {
  const talk = draft.kind === "talk";
  switch (step) {
    case "type":
      return made ? "What it is decides what else it needs." : "Pick one to start. You can change it later.";
    case "music":
      return talk
        ? "Songs play between the talk, so they still need a description."
        : "A name for the Radio page, and a description the AI picks songs from.";
    case "djs":
      return talk
        ? "Pick two or more. Tap one again to take them off."
        : "One DJ talks between the songs. A DJ can host any number of stations.";
    case "talking":
      return "Between songs, so every room hears it in step. Announcements always go first.";
    case "show":
      return "GuildFM plans each show and writes their script. You set the mix, what it's about, and how they get on.";
    case "extras":
      return "All optional. The defaults suit most stations.";
    case "review":
      return "Check it over. Nothing's saved until you create it.";
  }
}

/** What's missing before the step is done, or null. */
export function missing(step: Step, draft: Draft, voices: Voices | null): string | null {
  switch (step) {
    case "type":
      if (!draft.kind) return "Pick a kind of station to carry on.";
      if (draft.kind === "talk" && voices && !talkReady(voices)) return talkNotReady(voices);
      return null;
    case "music":
      if (!draft.name.trim()) return "Give it a name to carry on.";
      if (!draft.description.trim()) return "Say what it should play to carry on.";
      return null;
    case "djs": {
      const hosts = hostsOf(draft);
      if (draft.kind !== "talk") return hosts.length ? null : "Pick a DJ, or make a new one.";
      if (hosts.length === 0) return "Pick two or more hosts to carry on.";
      if (hosts.length === 1) return "Pick one more: a talk show needs two.";
      const openai = hosts.filter((dj) => !isEleven(dj.voice)).map((dj) => dj.name);
      if (openai.length) {
        const has = openai.length === 1 ? "has" : "have";
        return `${listed(openai)} ${has} an OpenAI voice. Change it to an ElevenLabs one, or take them off.`;
      }
      return null;
    }
    default:
      return null;
  }
}

/** Whether a talk show can be made: ElevenLabs is set up, with voices of its own. */
export const talkReady = (voices: Voices) => voices.elevenlabs_ready && voices.elevenlabs.length > 0;

export function talkNotReady(voices: Voices): string {
  if (!voices.elevenlabs_ready) {
    return "A talk show needs ElevenLabs voices, and ElevenLabs isn't set up: it needs ELEVENLABS_API_KEY in GuildFM's .env.";
  }
  return "A talk show needs ElevenLabs voices, and the ElevenLabs account has none of its own yet. Make some there first.";
}

/** How often a DJ talks, as the Talking step offers it. */
export const OFTEN = [
  { id: "every", label: "Every song", hint: "A line before each one", every: 1, unit: "tracks" as const },
  { id: "few", label: "Every few songs", hint: "About every three", every: 3, unit: "tracks" as const },
  { id: "now", label: "Now and then", hint: "About every 15 minutes", every: 15, unit: "minutes" as const },
];

export function oftenOf(every: number, unit: string): string {
  return OFTEN.find((o) => o.every === every && o.unit === unit)?.id ?? "custom";
}

export function oftenText(every: number, unit: string): string {
  const preset = OFTEN.find((o) => o.every === every && o.unit === unit);
  if (preset) return preset.label;
  const word = unit === "tracks" ? (every === 1 ? "song" : "songs") : every === 1 ? "minute" : "minutes";
  return every === 1 ? `Every ${word}` : `Every ${every} ${word}`;
}

export const SAYS = [
  {
    value: "announce" as const,
    label: "Just the songs",
    hint: "Short and simple: what played, and what's next.",
  },
  {
    value: "commentary" as const,
    label: "Songs and stories",
    hint: "Trivia, the weather, and the odd story about the song.",
  },
];

export const saysText = (style: string) => SAYS.find((s) => s.value === style)?.label ?? "";

/** ElevenLabs credits a minute of talk costs, as measured on eleven_v4 (talk.md). */
const CREDITS_A_MINUTE = 450;
/** Above this much talk, the slider turns red: costly, with very little music. */
export const HOT = 70;
export const LEAST_TALK = 20;

/** Roughly what an hour costs at `ratio` percent talk, to the nearest hundred credits. */
export function creditsAnHour(ratio: number): number {
  return Math.round(((ratio / 100) * 60 * CREDITS_A_MINUTE) / 100) * 100;
}

export const mixText = (ratio: number) =>
  ratio >= 100 ? "All talk" : `${ratio}% talk · ${100 - ratio}% music`;

export function hourText(ratio: number): string {
  if (ratio >= 100) return "In an hour: all talk. Only requests get played.";
  const talk = Math.round(ratio * 0.6);
  return `In an hour: about ${talk} minutes of talk and ${60 - talk} of music.`;
}

/** The extras that are on, in a list: "jingles, crossfade and knows what's going on". */
export function extrasOn(fields: StationFields): string[] {
  return [
    fields.jingles && "jingles",
    fields.crossfade && "crossfade",
    fields.global_awareness && "knows what's going on",
  ].filter((x): x is string => !!x);
}

export const sentence = (text: string) => (text ? text.charAt(0).toUpperCase() + text.slice(1) : text);

/** A colour for a DJ's initial, the same each time. */
const COLOURS = ["#ff8a3d", "#8db4ff", "#f5c451", "#e0a888", "#7fd1b9", "#c9b3ff"];
export function djColour(dj: { id: number | null; name: string }): string {
  if (dj.id !== null) return COLOURS[dj.id % COLOURS.length];
  let sum = 0;
  for (const c of dj.name) sum += c.charCodeAt(0);
  return COLOURS[sum % COLOURS.length];
}

/** The stations a DJ hosts other than `stationId`, by name. */
export function elsewhere(profile: DJProfile | undefined, stationId: number | null): string[] {
  return (profile?.stations ?? []).filter((s) => s.id !== stationId).map((s) => s.name);
}

/** One of the office's DJs as a station's DJ, with the details the editor sends. */
export const asStationDJ = (dj: DJProfile): StationDJ => ({
  id: dj.id,
  name: dj.name,
  personality: dj.personality,
  voice: dj.voice,
  pet_peeves: dj.pet_peeves,
  soft_spots: dj.soft_spots,
  obsession: dj.obsession,
});

/** A phrase to hear a DJ by, with tags for an ElevenLabs voice to act out. */
export function sampleLine(voice: string, style: "announce" | "commentary" = "announce"): string {
  const tags = isEleven(voice);
  if (style === "commentary") {
    return tags
      ? "That was Stevie Wonder. [sighs] Grey skies out there this afternoon, so here's a bit of Aretha to warm you up."
      : "That was Stevie Wonder. Grey skies out there this afternoon, so here's a bit of Aretha to warm you up.";
  }
  return tags
    ? "That was Stevie Wonder. [excited] Next up, a bit of Aretha to keep things moving."
    : "That was Stevie Wonder. Next up, a bit of Aretha to keep things moving.";
}
