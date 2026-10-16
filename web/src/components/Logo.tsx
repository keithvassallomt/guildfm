import { LOGO_PATH, LOGO_TRANSFORM, LOGO_VIEWBOX } from "./logoPath";
import styles from "./Logo.module.css";

/** The GuildFM logo: the building and its aerial over the name. It's filled with the current
 * text colour, so setting `color` recolours it; it's the accent orange unless told otherwise. */
export function Logo({ className = "" }: { className?: string }) {
  return (
    <svg className={`${styles.logo} ${className}`} viewBox={LOGO_VIEWBOX} role="img" aria-label="GuildFM">
      <path transform={LOGO_TRANSFORM} fill="currentColor" d={LOGO_PATH} />
    </svg>
  );
}
