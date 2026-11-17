import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api, errorText, type Station, type StationFields } from "../api";
import { Button, ButtonLink } from "../components/Button";
import { Dialog } from "../components/Dialog";
import { HelpLink } from "../components/HelpLink";
import { Icon } from "../components/Icon";
import { JingleList } from "../components/JingleList";
import { useLeaveGuard } from "../components/LeaveGuard";
import { StationCover } from "../components/StationCover";
import { FormError, TextField } from "../components/TextField";
import { useVoices } from "../components/useVoices";
import { HourPreview } from "./HourPreview";
import styles from "./Page.module.css";
import { DJs, talkable } from "./StationDJs";
import e from "./StationEditor.module.css";
import { Area, Section, SwitchRow } from "./StationParts";
import { TalkStation } from "./TalkStation";

const BACK = "/radio";

const BLANK: StationFields = {
  name: "",
  description: "",
  global_awareness: false,
  dj: false,
  dj_id: null,
  dj_name: "",
  personality: "",
  voice: "marin",
  talk_every: 3,
  talk_unit: "tracks",
  style: "commentary",
  announce_requests: true,
  jingles: true,
  crossfade: false,
  djs: [],
  dynamic: "",
  talk_station: false,
  talk_ratio: 40,
  script_prompt: "",
};

function fieldsOf(station: Station): StationFields {
  const fields = { ...BLANK };
  for (const key of Object.keys(BLANK) as (keyof StationFields)[]) {
    (fields as Record<string, unknown>)[key] = station[key];
  }
  return fields;
}

/** The form as it's sent: its DJs, if they're on, with the first also in the one-DJ fields
 * that the hour preview and the jingles read, and a talk station only if its DJs can talk. */
function sent(form: StationFields): StationFields {
  const djs = form.dj ? form.djs : [];
  const first = djs[0];
  return {
    ...form,
    djs,
    dj: djs.length > 0,
    dj_id: first?.id ?? null,
    dj_name: first?.name ?? "",
    personality: first?.personality ?? "",
    voice: first?.voice ?? "marin",
    talk_station: form.talk_station && talkable(djs),
  };
}

/** New AI station, or editing one (/radio/:id). */
export function StationEditor() {
  const { id } = useParams();
  const editing = id !== undefined;
  const navigate = useNavigate();
  const [form, setForm] = useState<StationFields | null>(editing ? null : BLANK);
  // The form as saved, to tell whether there are changes to lose.
  const [saved, setSaved] = useState<StationFields | null>(editing ? null : BLANK);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  // The form as it was when the hour preview was opened.
  const [previewing, setPreviewing] = useState<StationFields | null>(null);
  const [art, setArt] = useState<string | null>(null);
  const voices = useVoices();

  useEffect(() => {
    if (id === undefined) return;
    api<Station>("GET", `/stations/${id}`)
      .then((station) => {
        setForm(fieldsOf(station));
        setSaved(fieldsOf(station));
        setArt(station.art_url);
      })
      .catch((caught) => setError(errorText(caught)));
  }, [id]);

  const change = (changes: Partial<StationFields>) =>
    setForm((current) => current && { ...current, ...changes });

  const dirty = !!form && !!saved && JSON.stringify(form) !== JSON.stringify(saved);
  const { allow, dialog: leaving } = useLeaveGuard(dirty);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!form) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await api<Station>(
        editing ? "PUT" : "POST",
        editing ? `/stations/${id}` : "/stations",
        sent(form),
      );
      allow();
      navigate(BACK, { state: { said: editing ? "Saved." : `${saved.name} is ready to put on.` } });
    } catch (caught) {
      setError(errorText(caught));
      setBusy(false);
    }
  };

  const remove = async () => {
    try {
      await api("DELETE", `/stations/${id}`);
      allow();
      navigate(BACK, { state: { said: "Deleted." } });
    } catch (caught) {
      setDeleting(false);
      setError(errorText(caught));
    }
  };

  const ready =
    !!form &&
    !!form.name.trim() &&
    !!form.description.trim() &&
    (!form.dj || form.djs.every((dj) => !!dj.name.trim()));
  const talk = !!form && form.talk_station && form.dj && talkable(form.djs);
  const first = form?.dj ? form.djs[0] : undefined;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerStart}>
          <Link to={BACK} aria-label="Back to Radio" className={styles.iconLink}>
            <Icon name="back" />
          </Link>
          <h1 className={styles.title}>{editing ? "Edit station" : "New AI station"}</h1>
        </div>
        <HelpLink />
      </header>

      {!form && <FormError message={error} />}
      {form && (
        <form className={styles.columns} onSubmit={submit}>
          <div className={styles.stack}>
            <Section title="Station">
              <TextField
                label="Name"
                value={form.name}
                maxLength={100}
                placeholder="Lunchtime Grooves"
                onChange={(event) => change({ name: event.target.value })}
              />
              <Area
                label="What should it play?"
                value={form.description}
                rows={3}
                placeholder="Upbeat soul, funk and Motown for the lunch hour. Nothing too slow."
                onChange={(description) => change({ description })}
              />
              <SwitchRow
                label="Global awareness"
                hint="Uses the time of day, the weather where the office is, and music news, like an artist's passing or a song contest winner."
                checked={form.global_awareness}
                onChange={(global_awareness) => change({ global_awareness })}
              />
              <SwitchRow
                label="Crossfade between songs"
                hint="The speakers fade each song into the next, hiding the quiet at their starts and ends. The DJ and jingles fade in over the end of a song too."
                checked={form.crossfade}
                onChange={(crossfade) => change({ crossfade })}
              />
              {editing ? (
                <Cover
                  stationId={Number(id)}
                  url={art}
                  name={form.name.trim()}
                  description={form.description.trim()}
                  onPainted={setArt}
                  onError={setError}
                />
              ) : (
                <p className={styles.muted}>
                  Once it's created, OpenAI paints its cover from the name and description.
                </p>
              )}
            </Section>
            <p className={styles.muted}>
              The AI picks the songs from your description and what's played lately, and finds
              them on Spotify. Requests always play first, and thumbs down skip a song, but votes
              never change the station's taste.
            </p>
            <TalkStation form={form} voices={voices} onChange={change} />
            <Section title="Jingles">
              <SwitchRow
                label="Play jingles"
                hint="GuildFM's system idents and this station's own station idents, in the pause between songs. The AI chooses where."
                checked={form.jingles}
                onChange={(jingles) => change({ jingles })}
              />
              {form.jingles &&
                (editing ? (
                  <div className={e.field}>
                    <span className={e.label}>Station idents</span>
                    <JingleList
                      stationId={Number(id)}
                      empty="None yet. Without its own, the station plays GuildFM's system idents."
                      station={{
                        name: form.name,
                        description: form.description,
                        dj_name: first?.name ?? "",
                        personality: first?.personality ?? "",
                      }}
                    />
                  </div>
                ) : (
                  <p className={styles.muted}>
                    Create the station first, then come back to add its own station idents.
                  </p>
                ))}
            </Section>
          </div>

          <div className={styles.stack}>
            <DJs
              form={form}
              stationId={editing ? Number(id) : null}
              talk={talk}
              onChange={change}
              onError={setError}
            />
            <Button
              variant="secondary"
              block
              disabled={!ready || (talk && form.talk_ratio >= 100)}
              onClick={() => setPreviewing(sent(form))}
            >
              <Icon name="radio" size={18} />
              Preview an hour
            </Button>
            <FormError message={error} />
            <div className={e.actions}>
              <ButtonLink variant="secondary" block to={BACK}>
                Cancel
              </ButtonLink>
              <Button type="submit" block disabled={busy || !ready}>
                {editing ? "Save" : "Create station"}
              </Button>
            </div>
            {editing && (
              <Button variant="ghost" className={e.delete} onClick={() => setDeleting(true)}>
                Delete station
              </Button>
            )}
          </div>
        </form>
      )}

      {previewing && (
        <HourPreview
          open
          onClose={() => setPreviewing(null)}
          station={previewing}
          stationId={editing ? Number(id) : null}
        />
      )}

      {leaving}

      <Dialog open={deleting} onClose={() => setDeleting(false)} title="Delete this station?">
        <p className={styles.muted}>
          If it's on, nothing fills the gaps between requests until the queue runs out.
        </p>
        <div className={e.actions}>
          <Button variant="secondary" block onClick={() => setDeleting(false)}>
            Keep it
          </Button>
          <Button block onClick={remove}>
            Delete
          </Button>
        </div>
      </Dialog>
    </div>
  );
}

type CoverProps = {
  stationId: number;
  url: string | null;
  /** As they are in the form, saved or not: what the new cover is painted from. */
  name: string;
  description: string;
  onPainted: (url: string | null) => void;
  onError: (message: string | null) => void;
};

/** The station's cover, standing in for album art, and a button for another. */
function Cover({ stationId, url, name, description, onPainted, onError }: CoverProps) {
  const [busy, setBusy] = useState(false);

  const repaint = async () => {
    setBusy(true);
    onError(null);
    try {
      const station = await api<Station>("POST", `/stations/${stationId}/cover`, {
        name,
        description,
      });
      onPainted(station.art_url);
    } catch (caught) {
      onError(errorText(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={e.cover}>
      <StationCover url={url} className={e.coverArt} iconSize={34} />
      <div className={e.coverText}>
        <span className={e.rowHint}>
          Painted by OpenAI from the name and description above, saved or not. Saving a new
          name or description paints a new one, unless this cover was painted from them.
        </span>
        <Button variant="secondary" disabled={busy || !name || !description} onClick={repaint}>
          {busy ? "Painting, about half a minute..." : url ? "Paint another" : "Paint one"}
        </Button>
      </div>
    </div>
  );
}
