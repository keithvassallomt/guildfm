import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { api, type DJProfile, errorText, type Station, type StationFields } from "../api";
import { Button, ButtonLink } from "../components/Button";
import { HelpLink } from "../components/HelpLink";
import { Icon } from "../components/Icon";
import { useLeaveGuard } from "../components/LeaveGuard";
import { FormError } from "../components/TextField";
import { useVoices } from "../components/useVoices";
import { listed } from "../pages/announcementText";
import { HourPreview } from "../pages/HourPreview";
import {
  blankDraft,
  creditsAnHour,
  type Draft,
  extrasOn,
  hostsOf,
  type Kind,
  kindTitle,
  lead,
  missing,
  mixText,
  oftenText,
  question,
  saysText,
  sent,
  sentence,
  type Step,
  stepLabel,
  stepsFor,
} from "./kinds";
import { Avatar } from "./parts";
import { StepView } from "./StepView";
import w from "./Wizard.module.css";

type Stop = Step | "review";

/** Making a station, a step at a time: the type first, which decides the steps after it. */
export function NewStation() {
  const navigate = useNavigate();
  const voices = useVoices();
  const [known, setKnown] = useState<DJProfile[]>([]);
  const [draft, setDraft] = useState<Draft>(blankDraft);
  const [at, setAt] = useState(0);
  // The furthest step reached, which the stepper can go back to.
  const [reached, setReached] = useState(0);
  const [djEditing, setDJEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [made, setMade] = useState<Station | null>(null);
  const [previewing, setPreviewing] = useState<StationFields | null>(null);

  useEffect(() => {
    api<DJProfile[]>("GET", "/djs")
      .then(setKnown)
      .catch((caught) => setError(errorText(caught)));
  }, []);

  const stops: Stop[] = [...stepsFor(draft.kind), "review"];
  const index = Math.min(at, stops.length - 1);
  const stop = stops[index];
  const change = useCallback((changes: Partial<Draft>) => setDraft((current) => ({ ...current, ...changes })), []);
  const dirty = !made && JSON.stringify(draft) !== JSON.stringify(blankDraft());
  const { allow, dialog: leaving } = useLeaveGuard(dirty);

  const why =
    stop === "review"
      ? null
      : stop === "djs" && djEditing
        ? "Finish with the DJ's details, or cancel them, to carry on."
        : missing(stop, draft, voices);

  const go = (to: number) => {
    setAt(to);
    setError(null);
    window.scrollTo({ top: 0 });
  };

  const pick = (kind: Kind) => {
    if (kind === draft.kind) return;
    change({ kind });
    setReached(0);
  };

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const station = await api<Station>("POST", "/stations", sent(draft));
      allow();
      setMade(station);
      window.scrollTo({ top: 0 });
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  };

  const next = () => {
    if (why) return;
    if (stop === "review") {
      void create();
      return;
    }
    setReached(Math.max(reached, index + 1));
    go(index + 1);
  };

  const putOn = async (station: Station) => {
    setError(null);
    try {
      await api("POST", `/stations/${station.id}/play`);
      navigate("/radio", {
        state: { said: `${station.name} takes over from the next song. Requests still play first.` },
      });
    } catch (caught) {
      setError(errorText(caught));
    }
  };

  const stepText = made ? "Done" : `Step ${index + 1} of ${stops.length} · ${stepLabel(stop, draft.kind)}`;
  const progress = made ? 100 : ((index + 1) / stops.length) * 100;

  return (
    <div className={w.page}>
      <div className={w.top}>
        <div className={w.topRow}>
          <Link to="/radio" aria-label="Close" className={w.close}>
            <Icon name="close" />
          </Link>
          <span className={w.topText}>
            <span className={w.topTitle}>New station</span>
            <span className={w.topStep}>{stepText}</span>
          </span>
          <HelpLink />
        </div>
        <div className={w.progress} aria-hidden="true">
          <span style={{ width: `${progress}%` }} />
        </div>
      </div>

      <header className={w.head}>
        <div className={w.headText}>
          <span className={w.crumbs}>
            <Link to="/radio">Radio</Link> / New station
          </span>
          <h1 className={w.title}>New station</h1>
        </div>
        <div className={w.headEnd}>
          {!made && (
            <ButtonLink variant="ghost" to="/radio">
              Cancel
            </ButtonLink>
          )}
          <HelpLink />
        </div>
      </header>

      {!made && (
        <ol aria-label="Steps" className={w.steps}>
          {stops.map((key, i) => (
            <li key={key} className={`${w.stepItem} ${i < index ? w.done : ""}`}>
              <button
                type="button"
                className={w.stepButton}
                disabled={i > reached}
                aria-current={i === index ? "step" : undefined}
                onClick={() => go(i)}
              >
                <span className={w.dot}>{i < index ? <Icon name="check" size={14} strokeWidth={3} /> : i + 1}</span>
                {stepLabel(key, draft.kind)}
              </button>
              {i < stops.length - 1 && <span className={w.line} aria-hidden="true" />}
            </li>
          ))}
        </ol>
      )}

      <div className={w.body}>
        <div className={w.main}>
          {made ? (
            <Ready station={made} onPutOn={() => putOn(made)} />
          ) : (
            <>
              <div className={w.questionWrap}>
                <h2 className={w.question}>{question(stop, draft)}</h2>
                <p className={w.lead}>{lead(stop, draft, false)}</p>
              </div>
              {stop === "review" ? (
                <Review draft={draft} onChange={(step) => go(stops.indexOf(step))} onPreview={() => setPreviewing(sent(draft))} />
              ) : (
                <StepView
                  key={stop}
                  step={stop}
                  draft={draft}
                  place="wizard"
                  change={change}
                  voices={voices}
                  known={known}
                  stationId={null}
                  onPick={pick}
                  onError={setError}
                  onEditing={setDJEditing}
                />
              )}
            </>
          )}
          <FormError message={error} />
        </div>
        {!made && <SoFar draft={draft} />}
      </div>

      {!made && (
        <footer className={w.foot}>
          {index > 0 && (
            <Button variant="secondary" onClick={() => go(index - 1)}>
              Back
            </Button>
          )}
          <p className={w.why}>{why}</p>
          <Button className={w.next} disabled={!!why || busy} onClick={next}>
            {stop === "review" ? (
              busy ? (
                "Creating..."
              ) : (
                "Create station"
              )
            ) : (
              <>
                Next<span className={w.nextLong}>: {stepLabel(stops[index + 1], draft.kind)}</span>
              </>
            )}
          </Button>
        </footer>
      )}

      {previewing && (
        <HourPreview open onClose={() => setPreviewing(null)} station={previewing} stationId={null} />
      )}
      {leaving}
    </div>
  );
}

/** Every choice so far, each with Change, and the hour preview. */
function Review({ draft, onChange, onPreview }: { draft: Draft; onChange: (step: Step) => void; onPreview: () => void }) {
  const names = hostsOf(draft).map((dj) => dj.name);
  const rows: { label: string; value: string; step: Step }[] = [
    { label: "Type", value: draft.kind ? kindTitle(draft.kind) : "", step: "type" },
    { label: "Name", value: draft.name.trim(), step: "music" },
    { label: "Plays", value: draft.description.trim(), step: "music" },
  ];
  if (draft.kind === "dj") {
    rows.push({ label: "DJ", value: listed(names), step: "djs" });
    rows.push({
      label: "Talking",
      value: `${oftenText(draft.talk_every, draft.talk_unit)}. ${saysText(draft.style)}.${draft.announce_requests ? " Says who asked for a song." : ""}`,
      step: "talking",
    });
  }
  if (draft.kind === "talk") {
    rows.push({ label: "Hosts", value: listed(names), step: "djs" });
    rows.push({
      label: "Mix",
      value: `${mixText(draft.talk_ratio)}, about ${creditsAnHour(draft.talk_ratio).toLocaleString("en-GB")} credits an hour`,
      step: "show",
    });
    rows.push({ label: "About", value: draft.script_prompt.trim() || "Left to them", step: "show" });
    rows.push({ label: "How they get on", value: draft.dynamic.trim() || "Left to them", step: "show" });
  }
  const extras = extrasOn(draft);
  rows.push({ label: "Extras", value: extras.length ? `${sentence(listed(extras))}.` : "None", step: "extras" });
  const allTalk = draft.kind === "talk" && draft.talk_ratio >= 100;

  return (
    <>
      <dl className={w.review}>
        {rows.map((row) => (
          <div key={row.label} className={w.reviewRow}>
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
            <button
              type="button"
              className={w.change}
              aria-label={`Change ${row.label.toLowerCase()}`}
              onClick={() => onChange(row.step)}
            >
              Change
            </button>
          </div>
        ))}
      </dl>
      <div className={w.previewRow}>
        <Button variant="secondary" disabled={allTalk} onClick={onPreview}>
          <Icon name="radio" size={18} />
          Preview an hour
        </Button>
        <span className={w.hint}>
          {allTalk
            ? "There's no hour of songs to preview at all talk."
            : "See the songs it would pick, and where the talk goes. Takes about a minute."}
        </span>
      </div>
    </>
  );
}

/** "Your station": what's been chosen so far, filling in as it's made. */
function SoFar({ draft }: { draft: Draft }) {
  const hosts = hostsOf(draft);
  const extras = extrasOn(draft);
  const talk =
    draft.kind === null
      ? "Pick a type to start."
      : draft.kind === "music"
        ? "No DJ. Just music."
        : draft.kind === "dj"
          ? `${oftenText(draft.talk_every, draft.talk_unit)} · ${saysText(draft.style).toLowerCase()}`
          : `${mixText(draft.talk_ratio)} · about ${creditsAnHour(draft.talk_ratio).toLocaleString("en-GB")} credits an hour`;
  return (
    <aside className={w.aside} aria-label="Your station so far">
      <span className={w.asideTitle}>Your station</span>
      <div className={w.card}>
        <div className={w.cardTop}>
          <svg viewBox="0 0 300 150" className={w.rings} aria-hidden="true">
            {[22, 46, 70, 94].map((r) => (
              <circle key={r} cx="240" cy="40" r={r} />
            ))}
          </svg>
          <span className={w.kindChip}>{draft.kind ? kindTitle(draft.kind) : "New station"}</span>
          <span className={w.cardName}>{draft.name.trim() || "Untitled station"}</span>
        </div>
        <div className={w.cardBody}>
          <span className={w.cardPlays}>{draft.description.trim() || "What it plays shows here."}</span>
          {hosts.length > 0 && (
            <div className={w.cardDJs}>
              <span className={w.faces}>
                {hosts.map((dj) => (
                  <Avatar key={dj.id ?? dj.name} dj={dj} small />
                ))}
              </span>
              <span className={w.cardNames}>{listed(hosts.map((dj) => dj.name))}</span>
            </div>
          )}
          <span className={w.cardTalk}>{talk}</span>
          <span className={w.cardExtras}>{extras.length ? `With ${listed(extras)}` : "No extras"}</span>
        </div>
      </div>
      <p className={w.asideNote}>Nothing is saved until you create it.</p>
    </aside>
  );
}

/** Made: put it on, give it jingles, or go back to Radio. */
function Ready({ station, onPutOn }: { station: Station; onPutOn: () => void }) {
  return (
    <section className={w.ready} aria-labelledby="ready-title">
      <span className={w.readyIcon}>
        <Icon name="check" size={32} strokeWidth={2.6} />
      </span>
      <h2 id="ready-title" className={w.question}>
        {station.name} is ready
      </h2>
      <p className={w.readyText}>
        Its cover is being painted now. Put it on straight away, or find it under Radio.
      </p>
      <div className={w.readyButtons}>
        <Button onClick={onPutOn}>
          <Icon name="play" size={14} />
          Put it on now
        </Button>
        <ButtonLink variant="secondary" to={`/radio/${station.id}`} state={{ jingles: true }}>
          <Icon name="jingle" size={18} />
          Give it its own jingles
        </ButtonLink>
        <ButtonLink variant="secondary" to="/radio">
          Back to Radio
        </ButtonLink>
      </div>
    </section>
  );
}
