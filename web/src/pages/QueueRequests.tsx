import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  type Modifier,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { type ReactNode, useEffect, useState } from "react";
import type { QueueEntry, QueueSource } from "../api";
import { Credit } from "../components/Credit";
import { Icon } from "../components/Icon";
import { ago } from "../live/status";
import q from "./QueuePage.module.css";

export type Act = (method: "POST" | "DELETE", path: string, body?: unknown, done?: string) => void;

// Requests only move up and down the list.
const upAndDownOnly: Modifier = ({ transform }) => ({ ...transform, x: 0 });

type Props = { entries: QueueEntry[]; curator: boolean; act: Act };

/** The waiting requests. Curators reorder them by dragging (press and hold on a phone), or
 *  with the arrows in each request's tray. */
export function Requests({ entries, curator, act }: Props) {
  const [openTray, setOpenTray] = useState<number | null>(null);
  // Show a drop where it landed straight away, rather than waiting for the server.
  const [dropped, setDropped] = useState<number[] | null>(null);
  useEffect(() => setDropped(null), [entries]);

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 8 } }),
  );

  const byId = new Map(entries.map((entry) => [entry.id, entry]));
  const shown = dropped
    ? dropped.flatMap((id) => byId.get(id) ?? [])
    : entries;
  const ids = shown.map((entry) => entry.id);

  const moveTo = (entry: QueueEntry, position: number) =>
    act("POST", `/queue/${entry.id}/move`, { position });

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const to = ids.indexOf(Number(over.id));
    setDropped(arrayMove(ids, ids.indexOf(Number(active.id)), to));
    moveTo(byId.get(Number(active.id))!, to + 1);
  };

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      modifiers={[upAndDownOnly]}
      onDragStart={() => setOpenTray(null)}
      onDragEnd={onDragEnd}
    >
      <SortableContext items={ids} strategy={verticalListSortingStrategy} disabled={!curator}>
        <ol className={q.list}>
          {shown.map((entry, index) => (
            <Request
              key={entry.id}
              entry={entry}
              rank={index + 1}
              curator={curator}
              trayOpen={openTray === entry.id}
              onTray={() => setOpenTray(openTray === entry.id ? null : entry.id)}
              onMove={(position) => moveTo(entry, position)}
              last={index === shown.length - 1}
              act={act}
            />
          ))}
        </ol>
      </SortableContext>
    </DndContext>
  );
}

type RequestProps = {
  entry: QueueEntry;
  rank: number;
  last: boolean;
  curator: boolean;
  trayOpen: boolean;
  onTray: () => void;
  onMove: (position: number) => void;
  act: Act;
};

function Request({ entry, rank, last, curator, trayOpen, onTray, onMove, act }: RequestProps) {
  const title = entry.track.title;
  const sortable = useSortable({ id: entry.id, disabled: !curator });
  const voteFor = (value: -1 | 1) =>
    act("POST", `/queue/${entry.id}/vote`, { value: entry.my_vote === value ? 0 : value });
  const scoreClass = entry.my_vote === 1 ? q.up : entry.my_vote === -1 ? q.down : "";
  const canRemove = entry.mine || curator;

  return (
    <li
      ref={sortable.setNodeRef}
      style={{
        transform: CSS.Translate.toString(sortable.transform),
        transition: sortable.transition,
      }}
      className={`${q.request} ${curator ? q.draggable : ""} ${sortable.isDragging ? q.dragging : ""}`}
      // Pointer and touch only: keyboard users move requests with the tray's arrows.
      {...(curator ? sortable.listeners : {})}
    >
      <div className={q.requestTop}>
        <span className={q.rank}>{rank}</span>
        {entry.track.art_url ? (
          <img src={entry.track.art_url} alt="" className={q.art} draggable={false} />
        ) : (
          <span aria-hidden="true" className={q.art} />
        )}
        <div className={q.text}>
          <span className={q.titleLine}>
            <span className={q.title}>{title}</span>
            {entry.track.explicit && (
              <abbr title="Explicit" className={q.explicit}>
                E
              </abbr>
            )}
          </span>
          <span className={q.meta}>{entry.track.artists}</span>
        </div>
        <div className={q.votes}>
          <button
            type="button"
            aria-label={`Thumbs up for ${title}`}
            aria-pressed={entry.my_vote === 1}
            className={`${q.vote} ${entry.my_vote === 1 ? q.up : ""}`}
            onClick={() => voteFor(1)}
          >
            <Icon name="thumbUp" size={20} filled={entry.my_vote === 1} />
          </button>
          <span className={`${q.score} ${scoreClass}`} aria-label={`Score ${entry.score}`}>
            {entry.score > 0 ? `+${entry.score}` : entry.score}
          </span>
          <button
            type="button"
            aria-label={`Thumbs down for ${title}`}
            aria-pressed={entry.my_vote === -1}
            className={`${q.vote} ${entry.my_vote === -1 ? q.down : ""}`}
            onClick={() => voteFor(-1)}
          >
            <Icon name="thumbDown" size={20} filled={entry.my_vote === -1} />
          </button>
        </div>
      </div>
      <div className={q.requestBottom}>
        <span className={q.meta}>
          <Credit entry={entry} />
          {entry.pinned && " · placed by a curator"}
        </span>
        {entry.played_at && (
          <span className={q.recent}>
            <Icon name="clock" size={12} strokeWidth={2.4} />
            Played {ago(entry.played_at)}
          </span>
        )}
        {canRemove && (
          <Tray title={title} open={trayOpen} onToggle={onTray}>
            {curator && (
              <>
                <button
                  type="button"
                  aria-label={`Move ${title} up`}
                  disabled={rank === 1}
                  className={q.action}
                  onClick={() => onMove(rank - 1)}
                >
                  <Icon name="arrowUp" size={18} />
                </button>
                <button
                  type="button"
                  aria-label={`Move ${title} down`}
                  disabled={last}
                  className={q.action}
                  onClick={() => onMove(rank + 1)}
                >
                  <Icon name="arrowDown" size={18} />
                </button>
              </>
            )}
            <button
              type="button"
              aria-label={`Remove ${title}`}
              className={q.action}
              onClick={() => act("DELETE", `/queue/${entry.id}`, undefined, `Removed ${title}`)}
            >
              <Icon name="close" size={18} />
            </button>
          </Tray>
        )}
      </div>
    </li>
  );
}

type TrayProps = { title: string; open: boolean; onToggle: () => void; children: ReactNode };

/** A request's actions, tucked behind an arrow until wanted. They slide out to the left. */
function Tray({ title, open, onToggle, children }: TrayProps) {
  return (
    <div className={`${q.tray} ${open ? q.trayOpen : ""}`}>
      <div className={q.trayItems} inert={!open}>
        {children}
      </div>
      <button
        type="button"
        aria-expanded={open}
        aria-label={`${open ? "Hide" : "Show"} actions for ${title}`}
        className={q.trayToggle}
        onClick={onToggle}
      >
        <Icon name="back" size={18} />
      </button>
    </div>
  );
}

type UpcomingProps = { source: QueueSource; onThumb: (trackId: string, down: boolean) => void };

/** The playing playlist's next songs. A thumbs down counts towards skipping one this time round;
 *  there's no thumbs up, since the playlist keeps its own order. */
export function Upcoming({ source, onThumb }: UpcomingProps) {
  if (source.upcoming.length === 0) return null;
  return (
    <div className={q.upcoming}>
      <h3 className={q.upcomingTitle}>Then from {source.name}</h3>
      <ul className={q.list}>
        {source.upcoming.map(({ track, down, my_down }) => (
          <li key={track.id} className={`${q.request} ${q.fromPlaylist}`}>
            <div className={q.requestTop}>
              {track.art_url ? (
                <img src={track.art_url} alt="" className={q.art} />
              ) : (
                <span aria-hidden="true" className={q.art} />
              )}
              <div className={q.text}>
                <span className={q.title}>{track.title}</span>
                <span className={q.meta}>{track.artists}</span>
              </div>
              <span className={q.downCount} aria-label={`${down} of ${source.skip_at} thumbs down to skip`}>
                {down > 0 ? `${down}/${source.skip_at}` : ""}
              </span>
              <button
                type="button"
                aria-label={`Thumbs down for ${track.title}`}
                aria-pressed={my_down}
                className={`${q.vote} ${my_down ? q.down : ""}`}
                onClick={() => onThumb(track.id, !my_down)}
              >
                <Icon name="thumbDown" size={20} filled={my_down} />
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
