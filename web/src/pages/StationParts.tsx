import { type ReactNode, type Ref, useId } from "react";
import { Toggle } from "../components/Toggle";
import styles from "./Page.module.css";
import e from "./StationEditor.module.css";

/** One of the station editor's sections: a heading, anything beside it, and a card. */
export function Section({
  title,
  aside,
  children,
}: {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <section className={styles.section} aria-labelledby={id}>
      <div className={e.sectionTop}>
        <h2 id={id} className={styles.sectionTitle}>
          {title}
        </h2>
        {aside}
      </div>
      <div className={styles.card}>{children}</div>
    </section>
  );
}

type AreaProps = {
  label: string;
  value: string;
  rows: number;
  placeholder?: string;
  maxLength?: number;
  /** Shows how much of `maxLength` is used, beside the label. */
  counted?: boolean;
  hint?: string;
  disabled?: boolean;
  textareaRef?: Ref<HTMLTextAreaElement>;
  onChange: (value: string) => void;
};

export function Area({
  label,
  value,
  rows,
  placeholder,
  maxLength = 600,
  counted,
  hint,
  disabled,
  textareaRef,
  onChange,
}: AreaProps) {
  const id = useId();
  const hintId = useId();
  return (
    <div className={e.field}>
      <span className={e.labelRow}>
        <label htmlFor={id} className={e.label}>
          {label}
        </label>
        {counted && (
          <span className={e.count}>
            {value.length} / {maxLength}
          </span>
        )}
      </span>
      <textarea
        ref={textareaRef}
        id={id}
        rows={rows}
        maxLength={maxLength}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        aria-describedby={hint ? hintId : undefined}
        onChange={(event) => onChange(event.target.value)}
        className={e.textarea}
      />
      {hint && (
        <span id={hintId} className={e.rowHint}>
          {hint}
        </span>
      )}
    </div>
  );
}

type SwitchRowProps = {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
};

export function SwitchRow({ label, hint, checked, onChange }: SwitchRowProps) {
  const id = useId();
  return (
    <div className={e.row}>
      <span className={e.rowText}>
        <span id={id} className={e.rowLabel}>
          {label}
        </span>
        {hint && <span className={e.rowHint}>{hint}</span>}
      </span>
      <Toggle checked={checked} onChange={onChange} labelledBy={id} />
    </div>
  );
}

/** A switch beside a section's heading, such as "Use DJs". */
export function HeadingSwitch({
  label,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  const id = useId();
  return (
    <span className={`${e.headingSwitch} ${disabled ? e.off : ""}`}>
      <span id={id} className={e.rowHint}>
        {label}
      </span>
      <Toggle checked={checked} disabled={disabled} onChange={onChange} labelledBy={id} />
    </span>
  );
}
