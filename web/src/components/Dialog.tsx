import { type ReactNode, useEffect, useId, useRef } from "react";
import { Icon } from "./Icon";
import styles from "./Dialog.module.css";

type Props = {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  /** Nearly full height: for browsing, such as searching. */
  tall?: boolean;
  /** On wide screens, sit in the bottom-right corner, by the button that opened it. */
  corner?: boolean;
};

/** A modal: a sheet from the bottom on phones, a centred box on wider screens. */
export function Dialog({ open, onClose, title, children, tall = false, corner = false }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={`${styles.dialog} ${tall ? styles.tall : ""} ${corner ? styles.corner : ""}`}
      aria-labelledby={titleId}
      onClose={onClose}
      // A click on the dialog element itself is a click on the backdrop.
      onClick={(event) => event.target === ref.current && onClose()}
    >
      {open && (
        <div className={styles.body}>
          <div className={styles.header}>
            <h2 id={titleId} className={styles.title}>
              {title}
            </h2>
            {(tall || corner) && (
              <button type="button" aria-label="Close" className={styles.close} onClick={onClose}>
                <Icon name="close" size={20} />
              </button>
            )}
          </div>
          <div className={styles.content}>{children}</div>
        </div>
      )}
    </dialog>
  );
}
