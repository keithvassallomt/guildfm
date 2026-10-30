import { useEffect, useState } from "react";
import { api } from "../api";

// Asked once per page load, and again only if that failed.
let asked: Promise<string | null> | null = null;

/** The version of GuildFM running on the server, such as "0.1.0", once it's known. */
export function useVersion(): string | null {
  const [version, setVersion] = useState<string | null>(null);
  useEffect(() => {
    asked ??= api<{ version: string }>("GET", "/health").then(
      (health) => health.version,
      () => {
        asked = null;
        return null;
      },
    );
    let mounted = true;
    asked.then((found) => mounted && setVersion(found));
    return () => {
      mounted = false;
    };
  }, []);
  return version;
}
