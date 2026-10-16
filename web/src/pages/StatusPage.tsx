import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api, errorText, type Service, type ServiceState, type SystemStatus } from "../api";
import { Icon } from "../components/Icon";
import { StatusChip } from "../components/StatusChip";
import { FormError } from "../components/TextField";
import { ago } from "../live/status";
import styles from "./Page.module.css";
import s from "./StatusPage.module.css";

const REFRESH_MS = 15_000;

const STATE_WORDS: Record<ServiceState, string> = {
  ok: "Working",
  failing: "Needs a look",
  unused: "Not used yet",
  off: "Off",
};

/** "Fri 16 Oct, 09:12". */
const dayAndTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

const longDate = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "long" });

const gigabytes = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GB`;

/** When it last worked or failed, in words. */
function lately(service: Service): string | null {
  if (service.state === "failing" && service.failed_at) {
    const worked = service.ok_at ? `, last worked ${ago(service.ok_at)}` : "";
    return `Failed ${ago(service.failed_at)}${worked}`;
  }
  if (service.state === "ok" && service.ok_at) return `Last worked ${ago(service.ok_at)}`;
  return null;
}

function Credits({ used, limit, resets_at }: NonNullable<SystemStatus["credits"]>) {
  const share = limit ? Math.min(1, used / limit) : 1;
  return (
    <div className={s.credits}>
      <div
        className={s.meter}
        role="meter"
        aria-label="ElevenLabs credits used"
        aria-valuemin={0}
        aria-valuemax={limit}
        aria-valuenow={used}
      >
        <span
          className={share > 0.9 ? s.meterLow : s.meterFill}
          style={{ width: `${share * 100}%` }}
        />
      </div>
      <p className={s.when}>
        {used.toLocaleString()} of {limit.toLocaleString()} credits used this month
        {resets_at && `, more on ${longDate(resets_at)}`}
      </p>
    </div>
  );
}

/** For admins: whether GuildFM and everything it depends on is working, and what went wrong. */
export function StatusPage() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let showing = true;
    const load = () =>
      api<SystemStatus>("GET", "/status")
        .then((found) => {
          if (!showing) return;
          setStatus(found);
          setError(null);
        })
        .catch((caught) => showing && setError(errorText(caught)));
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      showing = false;
      window.clearInterval(timer);
    };
  }, []);

  const failing = status?.services.filter((service) => service.state === "failing").length ?? 0;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerStart}>
          <Link to="/admin" aria-label="Back to Admin" className={styles.iconLink}>
            <Icon name="back" />
          </Link>
          <h1 className={styles.title}>Status</h1>
        </div>
        {status && (
          <StatusChip tone={failing ? "warn" : "live"}>
            {failing ? `${failing} need${failing === 1 ? "s" : ""} a look` : "All working"}
          </StatusChip>
        )}
      </header>

      <FormError message={error} />

      {status && (
        <>
          <p className={styles.muted}>
            GuildFM {status.version}, running since {dayAndTime(status.started_at)}.{" "}
            {status.connected === 1 ? "1 browser has" : `${status.connected} browsers have`} it
            open.
          </p>

          <div className={styles.columns}>
            <section className={styles.section} aria-labelledby="services">
              <h2 id="services" className={styles.sectionTitle}>
                Speakers and services
              </h2>
              <ul className={s.services}>
                {status.services.map((service) => {
                  const when = lately(service);
                  return (
                    <li key={service.key} className={s.service}>
                      <span className={`${s.dot} ${s[service.state]}`} aria-hidden />
                      <div className={s.serviceText}>
                        <div className={s.serviceHead}>
                          <span className={s.name}>{service.name}</span>
                          <span className={service.state === "failing" ? s.stateBad : s.state}>
                            {STATE_WORDS[service.state]}
                          </span>
                        </div>
                        <p className={s.detail}>{service.detail}</p>
                        {when && <p className={s.when}>{when}</p>}
                        {service.key === "elevenlabs" && status.credits && (
                          <Credits {...status.credits} />
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>

            <div className={styles.stack}>
              <section className={styles.section} aria-labelledby="backups">
                <h2 id="backups" className={styles.sectionTitle}>
                  Backups
                </h2>
                <div className={styles.card}>
                  <p className={s.detail}>
                    {status.backups.latest_at
                      ? `${status.backups.count} kept, the latest ${dayAndTime(
                          status.backups.latest_at,
                        )}. One is made every day.`
                      : "None yet. GuildFM makes one every day while it runs."}
                  </p>
                  <p className={s.when}>
                    In <span className={s.path}>{status.backups.folder}</span>, with{" "}
                    {gigabytes(status.disk_free)} free on the disk.
                  </p>
                </div>
              </section>

              <section className={styles.section} aria-labelledby="problems">
                <h2 id="problems" className={styles.sectionTitle}>
                  Recent problems
                </h2>
                {status.problems.length ? (
                  <ul className={s.problems}>
                    {status.problems.map((problem) => (
                      <li key={`${problem.source} ${problem.message}`} className={s.problem}>
                        <span className={s.problemHead}>
                          <span className={problem.level === "error" ? s.stateBad : s.state}>
                            {ago(problem.at)}
                            {problem.count > 1 && `, ${problem.count} times`}
                          </span>
                          <span className={s.source}>
                            {problem.source.replace(/^guildfm\./, "")}
                          </span>
                        </span>
                        <span className={s.message}>{problem.message}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className={styles.card}>
                    <p className={styles.muted}>Nothing has gone wrong since GuildFM started.</p>
                  </div>
                )}
              </section>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
