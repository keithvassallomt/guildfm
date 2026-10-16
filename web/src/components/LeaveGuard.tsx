import { useEffect, useRef } from "react";
import { useBlocker } from "react-router";
import page from "../pages/Page.module.css";
import { Button } from "./Button";
import { Dialog } from "./Dialog";
import styles from "./LeaveGuard.module.css";

/** For a page with unsaved changes: asks before leaving it for elsewhere in GuildFM, and the
 * browser asks before the tab is closed or reloaded. Render `dialog`, and call `allow()` just
 * before leaving on purpose, such as after saving. */
export function useLeaveGuard(dirty: boolean) {
  const allowed = useRef(false);
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty && !allowed.current && currentLocation.pathname !== nextLocation.pathname,
  );

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = ""; // older browsers ask only with this set
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const stay = () => blocker.reset?.();
  const dialog = (
    <Dialog open={blocker.state === "blocked"} onClose={stay} title="Leave without saving?">
      <p className={page.muted}>Your changes on this page won't be kept.</p>
      <div className={styles.actions}>
        <Button variant="secondary" block onClick={stay}>
          Keep editing
        </Button>
        <Button block onClick={() => blocker.proceed?.()}>
          Leave
        </Button>
      </div>
    </Dialog>
  );

  return {
    allow: () => {
      allowed.current = true;
    },
    dialog,
  };
}
