import { useCallback, useEffect, useState } from "react";
import { api, type NowState } from "../api";
import { useLiveEvent } from "./LiveProvider";

/** Where the music is coming from, and the sources to switch between. */
export function useNow() {
  const [now, setNow] = useState<NowState | null>(null);

  const refresh = useCallback(() => {
    api<NowState>("GET", "/now")
      .then(setNow)
      .catch(() => {});
  }, []);

  useEffect(refresh, [refresh]);
  // Songs changing, and sources being switched, both come through as queue changes.
  useLiveEvent("queue", refresh);

  return { now, refresh };
}
