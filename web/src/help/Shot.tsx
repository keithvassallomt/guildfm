import { useEffect, useRef, useState } from "react";
import type { Role } from "../api";
import { Icon } from "../components/Icon";
import { useWide } from "../components/useWide";
import styles from "./Help.module.css";
import taken from "./shots.json";

type Size = "phone" | "desktop";
/** One screenshot: its size in CSS pixels, a version for caching, and whether it's the whole
 *  screen rather than a crop. */
type Variant = { w: number; h: number; v: string; screen: boolean };
/** Whose eyes a shot was taken through: a role, or a guest, signed out. */
export type Reading = Role | "guest";
type Taken = Record<string, Partial<Record<Size, Partial<Record<Reading, Variant>>>>>;

const SHOTS = taken as Taken;
const ROLES: Reading[] = ["guest", "user", "curator", "admin"];

/** The reader's own view if there is one, otherwise the nearest role below theirs, otherwise
 *  any. A shot is taken as each role it differs for. */
function pick(variants: Partial<Record<Reading, Variant>> | undefined, role: Reading) {
  if (!variants) return null;
  const below = ROLES.slice(0, ROLES.indexOf(role) + 1).reverse();
  const order = [...below, ...ROLES.filter((r) => !below.includes(r))];
  const found = order.find((r) => variants[r]);
  return found ? { role: found, ...variants[found]! } : null;
}

type Props = { name: string; alt: string; role: Reading };

/** A screenshot from tools/screenshots: taken on a phone for phones and on a desktop for
 *  desktops, through the reader's eyes. Whole screens open larger when tapped. */
export function Shot({ name, alt, role }: Props) {
  const size: Size = useWide() ? "desktop" : "phone";
  const [open, setOpen] = useState(false);
  const shot = pick(SHOTS[name]?.[size], role);
  if (!shot) {
    return import.meta.env.DEV ? <p className={styles.missing}>No screenshot called {name} yet.</p> : null;
  }

  const src = `/help/shots/${name}.${shot.role}.${size}.webp?v=${shot.v}`;
  const image = <img src={src} width={shot.w} height={shot.h} alt={alt} loading="lazy" />;
  return (
    <figure className={`${styles.shot} ${shot.screen ? styles.screen : ""}`}>
      {shot.screen ? (
        <button
          type="button"
          className={styles.enlarge}
          aria-label={`${alt}, larger`}
          onClick={() => setOpen(true)}
        >
          {image}
        </button>
      ) : (
        image
      )}
      <figcaption aria-hidden="true">{alt}</figcaption>
      {shot.screen && (
        <Larger open={open} onClose={() => setOpen(false)} src={src} alt={alt} shot={shot} />
      )}
    </figure>
  );
}

type LargerProps = { open: boolean; onClose: () => void; src: string; alt: string; shot: Variant };

/** The whole screenshot as large as the window allows. */
function Larger({ open, onClose, src, alt, shot }: LargerProps) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (open && dialog && !dialog.open) dialog.showModal();
    if (!open && dialog?.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={styles.larger}
      aria-label={alt}
      onClose={onClose}
      onClick={onClose}
    >
      {open && (
        <>
          <img src={src} width={shot.w} height={shot.h} alt={alt} />
          <button type="button" aria-label="Close" className={styles.close}>
            <Icon name="close" size={20} />
          </button>
        </>
      )}
    </dialog>
  );
}
