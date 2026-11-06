import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { api, type Note } from "../api";

// Only loaded when there's something to show, since it draws Markdown as the help does.
const NewsDialog = lazy(() => import("./NewsDialog"));

/** "What's new" after GuildFM updates, once for each person. It's asked for when GuildFM opens
 *  and each time someone comes back to it, so nobody has to sign in again to see it, and a page
 *  left open across an update shows it too. */
export function WhatsNew() {
  const [notes, setNotes] = useState<Note[]>([]);
  // Closed on this page, so a check that crosses with saying so doesn't bring them back.
  const closed = useRef(new Set<string>());

  const check = useCallback(() => {
    api<{ notes: Note[] }>("GET", "/me/news")
      .then((news) => setNotes(news.notes.filter((note) => !closed.current.has(note.version))))
      .catch(() => {});
  }, []);

  useEffect(() => {
    check();
    const onVisible = () => {
      if (document.visibilityState === "visible") check();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [check]);

  const close = useCallback(() => {
    setNotes((shown) => {
      for (const note of shown) closed.current.add(note.version);
      return [];
    });
    api("POST", "/me/news").catch(() => {});
  }, []);

  if (notes.length === 0) return null;
  return (
    <Suspense fallback={null}>
      <NewsDialog notes={notes} onClose={close} />
    </Suspense>
  );
}
