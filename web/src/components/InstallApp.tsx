import { useEffect, useState } from "react";
import page from "../pages/Page.module.css";
import { Button } from "./Button";

/** Chrome's and Edge's offer to install the app, which they make once a page has loaded. */
type InstallPrompt = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

// Kept from page load, since the browser makes its offer before this section is ever shown.
let offer: InstallPrompt | null = null;
const listeners = new Set<() => void>();
const changed = () => listeners.forEach((listener) => listener());

window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault(); // offered from here instead of the browser's own banner
  offer = event as InstallPrompt;
  changed();
});
window.addEventListener("appinstalled", () => {
  offer = null;
  changed();
});

const installed = () =>
  window.matchMedia("(display-mode: standalone)").matches ||
  (navigator as Navigator & { standalone?: boolean }).standalone === true;

// iPads say they're Macs, but Macs don't have touch screens.
const apple = () =>
  /iPhone|iPad|iPod/.test(navigator.userAgent) ||
  (navigator.userAgent.includes("Macintosh") && navigator.maxTouchPoints > 1);

/** How to put GuildFM on this device as an app, unless it's already running as one. */
export function InstallApp() {
  const [, render] = useState(0);
  useEffect(() => {
    const listener = () => render((count) => count + 1);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  if (installed()) return null;

  const install = async () => {
    if (!offer) return;
    await offer.prompt();
    if ((await offer.userChoice).outcome === "accepted") offer = null;
    changed();
  };

  return (
    <section className={page.section} aria-labelledby="install">
      <h2 id="install" className={page.sectionTitle}>
        GuildFM as an app
      </h2>
      <div className={page.card}>
        {offer ? (
          <>
            <p className={page.muted}>
              Install it to open GuildFM from your home screen or dock, in its own window.
            </p>
            <Button variant="secondary" onClick={install}>
              Install GuildFM
            </Button>
          </>
        ) : apple() ? (
          <p className={page.muted}>
            In Safari, tap the Share button, then Add to Home Screen. GuildFM then opens from your
            home screen in its own window.
          </p>
        ) : (
          <p className={page.muted}>
            Your browser's menu can add GuildFM to your home screen or install it as an app.
          </p>
        )}
      </div>
    </section>
  );
}
