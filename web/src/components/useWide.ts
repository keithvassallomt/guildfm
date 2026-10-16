import { useEffect, useState } from "react";

const WIDE = "(min-width: 768px)";

/** Whether the window is wide enough for the desktop layout (the sidebar's breakpoint). */
export function useWide(): boolean {
  const [wide, setWide] = useState(() => window.matchMedia(WIDE).matches);

  useEffect(() => {
    const query = window.matchMedia(WIDE);
    const change = () => setWide(query.matches);
    query.addEventListener("change", change);
    return () => query.removeEventListener("change", change);
  }, []);

  return wide;
}
