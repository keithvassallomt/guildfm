import { useCallback, useEffect, useState } from "react";
import { api, type QueueState } from "../api";
import { useLiveEvent } from "./LiveProvider";

/** The queue as the signed-in person sees it, fetched again whenever it changes. */
export function useQueue() {
  const [queue, setQueue] = useState<QueueState | null>(null);

  const refresh = useCallback(() => {
    api<QueueState>("GET", "/queue")
      .then(setQueue)
      .catch(() => {});
  }, []);

  useEffect(refresh, [refresh]);
  // The server only says that something changed; each person's view has their own votes.
  useLiveEvent("queue", refresh);

  return { queue, apply: setQueue, refresh };
}
