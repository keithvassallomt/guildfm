import { useSearchParams } from "react-router";
import { useQueue } from "../live/useQueue";
import { type SearchChanges, SongSearch } from "../search/SongSearch";
import styles from "./Page.module.css";

export function SearchPage() {
  // The search lives in the address, so Back and refresh keep it.
  const [params, setParams] = useSearchParams();
  const { queue, apply } = useQueue();

  const update = (changes: SearchChanges) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setParams(next, { replace: true });
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Search</h1>
      </header>
      <SongSearch
        query={params.get("q") ?? ""}
        artist={params.get("artist")}
        onChange={update}
        queue={queue}
        onQueue={apply}
      />
    </div>
  );
}
