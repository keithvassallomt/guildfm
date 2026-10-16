import { useCallback, useEffect, useRef, useState } from "react";
import { api, type History, type Play } from "../api";
import { useLiveEvent } from "./LiveProvider";

const PAGE = 10;

/** Today's plays, newest first, with more fetched on request. */
export function useHistory() {
  const [plays, setPlays] = useState<Play[] | null>(null);
  const [more, setMore] = useState(false);
  const shown = useRef(PAGE);

  // Fetches as many as are showing, so a new play doesn't fold away what was opened.
  const refresh = useCallback(() => {
    api<History>("GET", `/history?limit=${Math.min(shown.current, 100)}`)
      .then((page) => {
        setPlays(page.plays);
        setMore(page.more);
      })
      .catch(() => {});
  }, []);

  useEffect(refresh, [refresh]);
  useLiveEvent("queue", refresh);

  const showMore = useCallback(async () => {
    const last = plays?.at(-1);
    if (!last) return;
    const page = await api<History>("GET", `/history?limit=${PAGE}&before=${last.id}`);
    shown.current += page.plays.length;
    setPlays((current) => [...(current ?? []), ...page.plays]);
    setMore(page.more);
  }, [plays]);

  return { plays, more, showMore };
}
