/* Help topics are Markdown files in ./topics, one per topic, opening with front matter:

     ---
     title: Making announcements
     summary: One line on what it helps with.
     area: announcements
     order: 1
     needs: announce
     pages: /admin/announcements, /admin/announcements/:id
     ---

   `needs` (optional) is the permission a reader needs to see the topic at all, `public: yes`
   opens it to people who haven't signed in, and `pages` lists the app's pages whose ? opens it. In the text, `![What it shows](shot:name)` is a screenshot from
   tools/screenshots, `[words](topic:id)` links to another topic, a quote is a tip, and blocks
   between `::: needs x`, `::: lacks x`, `::: phone` or `::: desktop` and `:::` show only to
   people who can (or can't) x, or only on that size of screen. */

import { matchPath } from "react-router";
import type { Permission } from "../api";

/** The help's areas, in the order they're listed. One shows once it has a topic the reader can
 *  see. */
export const AREAS = [
  { id: "start", title: "Getting started" },
  { id: "listening", title: "Listening and requesting" },
  { id: "music", title: "Choosing the music" },
  { id: "playlists", title: "Playlists" },
  { id: "radio", title: "Radio" },
  { id: "lineups", title: "Line-ups" },
  { id: "announcements", title: "Announcements" },
  { id: "running", title: "Running GuildFM" },
] as const;

export type AreaId = (typeof AREAS)[number]["id"];

export type Topic = {
  /** From its file name: topics/requesting.md is "requesting", at /help/requesting. */
  id: string;
  title: string;
  /** One line on what it helps with, under its title. */
  summary: string;
  area: AreaId;
  /** Its place in its area, lowest first. */
  order: number;
  /** Only people who can do this read it. */
  needs: Permission | null;
  /** Readable before signing in, from the sign-in page. */
  public: boolean;
  /** The app's pages it's the help for, such as /admin/announcements/:id, for their ? button. */
  pages: string[];
  /** Markdown, with `::: needs x` and `::: lacks x` blocks. */
  body: string;
};

/** Splits a topic file into its front matter (`key: value` lines between `---`) and body. */
function parse(path: string, text: string): Topic {
  const id = path.replace(/^.*\/(.+)\.md$/, "$1");
  const found = text.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!found) throw new Error(`Help topic ${id} has no front matter`);
  const meta = Object.fromEntries(
    found[1].split("\n").map((line) => {
      const at = line.indexOf(":");
      return [line.slice(0, at).trim(), line.slice(at + 1).trim()];
    }),
  );
  if (!AREAS.some((area) => area.id === meta.area)) {
    throw new Error(`Help topic ${id} is in an unknown area, ${meta.area}`);
  }
  return {
    id,
    title: meta.title,
    summary: meta.summary ?? "",
    area: meta.area as AreaId,
    order: Number(meta.order ?? 100),
    needs: (meta.needs as Permission | undefined) ?? null,
    public: meta.public === "yes",
    pages: meta.pages ? meta.pages.split(",").map((page: string) => page.trim()) : [],
    body: found[2],
  };
}

const files = import.meta.glob("./topics/*.md", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

export const TOPICS: Topic[] = Object.entries(files)
  .map(([path, text]) => parse(path, text))
  .sort((a, b) => a.order - b.order || a.title.localeCompare(b.title));

export type Can = (permission: Permission) => boolean;
export type Size = "phone" | "desktop";

/** The topic's text as someone sees it: a `::: needs x` block only for people who can x, a
 *  `::: lacks x` block only for people who can't, and `::: phone` and `::: desktop` blocks only
 *  on that size of screen (both when `size` is null, as when searching). Blocks can sit inside
 *  each other. */
export function readable(body: string, can: Can, size: Size | null): string {
  const shown: string[] = [];
  const open: boolean[] = [];
  for (const line of body.split("\n")) {
    const block = line.match(/^:::\s*(needs|lacks)\s+([a-z_]+)\s*$/);
    const screen = line.match(/^:::\s*(phone|desktop)\s*$/);
    if (block) {
      const able = can(block[2] as Permission);
      open.push(block[1] === "needs" ? able : !able);
    } else if (screen) {
      open.push(size === null || screen[1] === size);
    } else if (/^:::\s*$/.test(line)) {
      open.pop();
    } else if (open.every(Boolean)) {
      shown.push(line);
    }
  }
  return shown.join("\n");
}

/** Someone signed out (a guest) reads only the public topics. */
export const canRead = (topic: Topic, can: Can, guest = false) =>
  guest ? topic.public : !topic.needs || can(topic.needs);

/** The topics that are help for an address in the app, such as /admin/announcements/4. */
export const topicsFor = (topics: Topic[], path: string) =>
  topics.filter((topic) => topic.pages.some((page) => matchPath(page, path)));

/** Plain words, for searching: no markup, pictures or link addresses. */
export function words(markdown: string): string {
  return markdown
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[*_`#>]/g, " ")
    .replace(/\s+/g, " ")
    .toLowerCase();
}

export const slug = (text: string) =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
