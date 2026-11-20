import { type ReactNode, useCallback, useEffect, useId, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router";
import { api, type DJProfile, errorText, type Station } from "../api";
import { Button } from "../components/Button";
import { Dialog } from "../components/Dialog";
import { HelpLink } from "../components/HelpLink";
import { Icon } from "../components/Icon";
import { JingleList } from "../components/JingleList";
import { usePreview } from "../components/PreviewButton";
import { StationCover } from "../components/StationCover";
import { FormError } from "../components/TextField";
import { useToast } from "../components/Toast";
import { useVoices } from "../components/useVoices";
import { useLiveEvent } from "../live/LiveProvider";
import { listed } from "../pages/announcementText";
import { HourPreview } from "../pages/HourPreview";
import { ChangeDialog } from "./ChangeDialog";
import {
  creditsAnHour,
  extrasOn,
  hostsOf,
  draftOf,
  KINDS,
  kindOf,
  mixText,
  oftenText,
  saysText,
  sentence,
  type Step,
} from "./kinds";
import { Avatar, hearLabel, useHear } from "./parts";
import { HourStrip } from "./ShowStep";
import p from "./StationPage.module.css";

/** A station: what it is, a card for each part with Change, and what only a made station has,
 * its cover, its own jingles and Delete. */
export function StationPage() {
  const { id } = useParams();
  const stationId = Number(id);
  const location = useLocation();
  const navigate = useNavigate();
  const [station, setStation] = useState<Station | null>(null);
  const [known, setKnown] = useState<DJProfile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [changing, setChanging] = useState<Step | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const { show, toast } = useToast();
  const voices = useVoices();
  // Sent here by the wizard's "Give it its own jingles".
  const [generate] = useState(() => (location.state as { jingles?: boolean } | null)?.jingles === true);

  const load = useCallback(() => {
    api<Station>("GET", `/stations/${stationId}`)
      .then(setStation)
      .catch((caught) => setError(errorText(caught)));
  }, [stationId]);
  const loadDJs = useCallback(() => {
    api<DJProfile[]>("GET", "/djs")
      .then(setKnown)
      .catch(() => {});
  }, []);
  useEffect(load, [load]);
  useEffect(loadDJs, [loadDJs]);
  // Once read, so going back or reloading doesn't open the jingle generator again.
  useEffect(() => {
    if (generate) navigate(location.pathname, { replace: true, state: null });
  }, [generate, navigate, location.pathname]);
  // A new cover, or it going on or off air.
  useLiveEvent("queue", load);

  if (!station) {
    return (
      <div className={p.page}>
        <header className={p.header}>
          <Link to="/radio" aria-label="Back to Radio" className={`${p.back} ${p.always}`}>
            <Icon name="back" />
          </Link>
          <span className={p.headText} />
          <HelpLink />
        </header>
        <FormError message={error} />
      </div>
    );
  }

  const kind = kindOf(station);
  const about = KINDS.find((k) => k.kind === kind);
  const editable = station.kind === "custom";
  const allTalk = kind === "talk" && station.talk_ratio >= 100;

  const putOn = async () => {
    setError(null);
    try {
      setStation(await api<Station>("POST", `/stations/${station.id}/play`));
      show(`${station.name} takes over from the next song. Requests still play first.`);
    } catch (caught) {
      setError(errorText(caught));
    }
  };

  const remove = async () => {
    try {
      await api("DELETE", `/stations/${station.id}`);
      navigate("/radio", { state: { said: "Deleted." } });
    } catch (caught) {
      setDeleting(false);
      setError(errorText(caught));
    }
  };

  const actions = (
    <>
      <Button variant="secondary" disabled={allTalk} onClick={() => setPreviewing(true)}>
        <Icon name="radio" size={18} />
        Preview an hour
      </Button>
      {station.playing ? (
        <span className={p.onAir}>On air</span>
      ) : (
        <Button className={p.putOn} onClick={putOn}>
          <Icon name="play" size={14} />
          Put it on
        </Button>
      )}
    </>
  );

  return (
    <div className={p.page}>
      <header className={p.header}>
        <Link to="/radio" aria-label="Back to Radio" className={p.back}>
          <Icon name="back" />
        </Link>
        <div className={p.headText}>
          <span className={p.crumbs}>
            <Link to="/radio">Radio</Link> / {station.name}
          </span>
          <div className={p.titleRow}>
            <h1 className={p.title}>{station.name}</h1>
            <span className={p.kindChip}>{about?.title}</span>
          </div>
        </div>
        <div className={p.headEnd}>
          <div className={p.wideActions}>{actions}</div>
          <HelpLink />
        </div>
      </header>

      <div className={p.columns}>
        <div className={p.parts}>
          <Part title="Type" change={editable ? () => setChanging("type") : undefined} label="Change the type">
            <span className={p.big}>{about?.title}</span>
            <span className={p.muted}>{about?.text}</span>
          </Part>

          <Part
            title="Name and music"
            change={editable ? () => setChanging("music") : undefined}
            label="Change the name and music"
          >
            <span className={p.big}>{station.name}</span>
            <span className={p.text}>{station.description}</span>
          </Part>

          {kind !== "music" && (
            <DJs station={station} change={editable ? () => setChanging("djs") : undefined} onError={setError} />
          )}

          {kind === "dj" && (
            <Part title="Talking" change={editable ? () => setChanging("talking") : undefined} label="Change how the DJ talks">
              <span className={p.strong}>
                {oftenText(station.talk_every, station.talk_unit)}. {saysText(station.style)}.
              </span>
              <span className={p.muted}>
                {station.announce_requests ? "Says who asked for a song." : "Doesn't say who asked for a song."}
              </span>
            </Part>
          )}

          {kind === "talk" && (
            <Show station={station} change={editable ? () => setChanging("show") : undefined} onError={setError} />
          )}

          <Part title="Extras" change={editable ? () => setChanging("extras") : undefined} label="Change the extras">
            <span className={p.text}>
              {extrasOn(station).length ? `${sentence(listed(extrasOn(station)))}.` : "None."}
            </span>
          </Part>
          <FormError message={error} />
        </div>

        <div className={p.side}>
          <Cover station={station} onPainted={setStation} onError={setError} />
          {editable && (
            <section className={p.card} aria-labelledby="own-jingles">
              <h2 id="own-jingles" className={p.sideTitle}>
                Its own jingles
              </h2>
              <JingleList
                stationId={station.id}
                startGenerating={generate}
                empty={
                  station.jingles
                    ? "None yet. Without its own, it plays GuildFM's system idents."
                    : "None yet. Play jingles is off under Extras, so it plays none at all."
                }
                station={{
                  name: station.name,
                  description: station.description,
                  dj_name: hostsOf(draftOf(station))[0]?.name ?? "",
                  personality: hostsOf(draftOf(station))[0]?.personality ?? "",
                }}
              />
            </section>
          )}
          {editable && (
            <Button variant="secondary" className={p.delete} onClick={() => setDeleting(true)}>
              Delete station
            </Button>
          )}
        </div>
      </div>

      <div className={p.bar}>{actions}</div>

      {changing && (
        <ChangeDialog
          station={station}
          start={changing}
          voices={voices}
          known={known}
          onClose={() => setChanging(null)}
          onSaved={(result, said) => {
            setStation(result);
            setChanging(null);
            loadDJs();
            show(said);
          }}
        />
      )}
      {previewing && (
        <HourPreview open onClose={() => setPreviewing(false)} station={station} stationId={station.id} />
      )}
      <Dialog open={deleting} onClose={() => setDeleting(false)} title="Delete this station?">
        <p className={p.muted}>
          Its own jingles go with it. If it's on, nothing fills the gaps between requests until the
          queue runs out.{kind === "music" ? "" : " Its DJs stay, for other stations."}
        </p>
        <div className={p.confirm}>
          <Button variant="secondary" block onClick={() => setDeleting(false)}>
            Keep it
          </Button>
          <Button block onClick={remove}>
            Delete
          </Button>
        </div>
      </Dialog>
      {toast}
    </div>
  );
}

/** One part of the station, with Change. */
function Part({
  title,
  label,
  change,
  children,
}: {
  title: string;
  label: string;
  change?: () => void;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <section className={p.part} aria-labelledby={id}>
      <div className={p.partTop}>
        <h2 id={id} className={p.partTitle}>
          {title}
        </h2>
        {change && (
          <button type="button" className={p.change} aria-label={label} onClick={change}>
            Change
          </button>
        )}
      </div>
      {children}
    </section>
  );
}

function DJs({ station, change, onError }: { station: Station; change?: () => void; onError: (m: string | null) => void }) {
  const talk = kindOf(station) === "talk";
  const hosts = hostsOf(draftOf(station));
  const { hear, state } = useHear(onError);
  return (
    <Part title={talk ? "Hosts" : "DJ"} change={change} label={talk ? "Change the hosts" : "Change the DJ"}>
      <div className={p.djs}>
        {hosts.map((dj) => {
          const key = String(dj.id);
          const hearing = state(key);
          return (
            <div key={key} className={p.dj}>
              <Avatar dj={dj} small />
              <span className={p.strong}>{dj.name}</span>
              <button
                type="button"
                className={p.hear}
                aria-label={hearing === "idle" ? `Hear ${dj.name}` : `${hearLabel(hearing)}, ${dj.name}`}
                onClick={() => hear(key, dj)}
              >
                <Icon name={hearing === "playing" ? "stop" : "headphones"} size={16} />
                {hearLabel(hearing)}
              </button>
            </div>
          );
        })}
      </div>
      <span className={p.muted}>Changing a DJ's personality or voice changes them on every station they host.</span>
    </Part>
  );
}

function Show({ station, change, onError }: { station: Station; change?: () => void; onError: (m: string | null) => void }) {
  const { status, play, stop } = usePreview();
  const [problem, setProblem] = useState<string | null>(null);
  const together = () => {
    if (status !== "idle") {
      stop();
      return;
    }
    onError(null);
    setProblem(null);
    play("/stations/together", {
      name: station.name,
      djs: station.djs,
      dynamic: station.dynamic,
      script_prompt: station.script_prompt,
    }).catch((caught) => setProblem(errorText(caught)));
  };
  return (
    <Part title="The show" change={change} label="Change the show">
      <div className={p.mix}>
        <HourStrip ratio={station.talk_ratio} />
        <span className={p.mono}>
          {mixText(station.talk_ratio)} · about {creditsAnHour(station.talk_ratio).toLocaleString("en-GB")} credits an hour
        </span>
      </div>
      <div className={p.pair}>
        <span className={p.small}>What it's about</span>
        <span className={`${p.text} ${p.clamp3}`}>{station.script_prompt || "Left to them."}</span>
      </div>
      <div className={p.pair}>
        <span className={p.small}>How they get on</span>
        <span className={`${p.text} ${p.clamp2}`}>{station.dynamic || "Left to them."}</span>
      </div>
      <div className={p.showFoot}>
        <Button variant="secondary" onClick={together}>
          <Icon name={status === "playing" ? "stop" : "headphones"} size={16} />
          {status === "loading"
            ? "Writing and voicing, about half a minute..."
            : status === "playing"
              ? "Stop"
              : "Hear them together"}
        </Button>
        <span className={p.muted}>
          {station.announce_requests ? "Says who asked for a song." : "Doesn't say who asked for a song."}
        </span>
      </div>
      <FormError message={problem} />
    </Part>
  );
}

/** The station's cover, standing in for album art, and a button for another. */
function Cover({
  station,
  onPainted,
  onError,
}: {
  station: Station;
  onPainted: (station: Station) => void;
  onError: (message: string | null) => void;
}) {
  const [busy, setBusy] = useState(false);
  const repaint = async () => {
    setBusy(true);
    onError(null);
    try {
      onPainted(await api<Station>("POST", `/stations/${station.id}/cover`));
    } catch (caught) {
      onError(errorText(caught));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className={`${p.card} ${p.cover}`} aria-labelledby="cover-title">
      <StationCover url={station.art_url} className={p.coverArt} iconSize={34} />
      <div className={p.coverText}>
        <h2 id="cover-title" className={p.sideTitle}>
          Cover
        </h2>
        <span className={p.muted}>
          Painted from the name and music. A new name or music paints a new one when it's saved.
        </span>
        {station.kind === "custom" && (
          <Button variant="secondary" disabled={busy} onClick={repaint}>
            {busy ? "Painting, about half a minute..." : station.art_url ? "Paint another" : "Paint one"}
          </Button>
        )}
      </div>
    </section>
  );
}
