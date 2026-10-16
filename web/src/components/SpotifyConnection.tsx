import { useCallback, useEffect, useState } from "react";
import { api, errorText, type SpotifyAccount } from "../api";
import page from "../pages/Page.module.css";
import { Button } from "./Button";
import { Icon } from "./Icon";
import spotify from "./SpotifyConnection.module.css";
import { FormError } from "./TextField";

const THIS_MACHINE = ["127.0.0.1", "localhost", "[::1]"];

const longDate = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });

/** The Spotify account curators import playlists from. */
export function SpotifyConnection() {
  const [account, setAccount] = useState<SpotifyAccount | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const load = useCallback(() => {
    api<SpotifyAccount>("GET", "/spotify/account")
      .then(setAccount)
      .catch((caught) => setError(errorText(caught)));
  }, []);

  useEffect(() => {
    load();
    // Connecting happens in another tab, so check again on coming back to this one.
    const onVisible = () => document.visibilityState === "visible" && load();
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [load]);

  const connect = async () => {
    // Open the tab straight away, inside the click, so pop-up blockers allow it.
    const tab = window.open("about:blank", "_blank");
    if (tab) tab.opener = null;
    try {
      const { url } = await api<{ url: string }>("POST", "/spotify/connect");
      if (tab) tab.location.href = url;
      else window.location.assign(url);
    } catch (caught) {
      tab?.close();
      setError(errorText(caught));
    }
  };

  const disconnect = async () => {
    try {
      await api("DELETE", "/spotify/account");
      setConfirming(false);
      load();
    } catch (caught) {
      setError(errorText(caught));
    }
  };

  const onThisMachine = THIS_MACHINE.includes(window.location.hostname);
  const here = `http://127.0.0.1:${window.location.port || "80"}/admin`;

  return (
    <section className={page.section} aria-labelledby="connections">
      <h2 id="connections" className={page.sectionTitle}>
        Connections
      </h2>
      <div className={page.card}>
        <div className={spotify.connection}>
          <Icon name="spotify" />
          <span className={spotify.linkText}>
            <span className={spotify.linkTitle}>Spotify account</span>
            <span className={spotify.linkHint}>
              {account?.connected
                ? `Connected as ${account.display_name}${
                    account.playlists !== null ? `, ${account.playlists} playlists` : ""
                  }`
                : "Not connected"}
            </span>
          </span>
        </div>

        {account?.connected && account.reconnect_by && (
          <p className={account.reconnect_soon ? spotify.soon : page.muted}>
            {account.reconnect_soon ? "Reconnect soon: " : ""}Spotify asks for the account to be
            connected again by {longDate(account.reconnect_by)}.
          </p>
        )}
        {account && !account.connected && (
          <p className={page.muted}>
            Curators import playlists from this account. Only playlists it owns or collaborates
            on can be imported.
          </p>
        )}
        {account?.problem && <p className={spotify.soon}>{account.problem}</p>}

        {onThisMachine ? (
          <div className={spotify.buttons}>
            <Button variant={account?.connected ? "secondary" : "primary"} onClick={connect}>
              {account?.connected ? "Reconnect" : "Connect Spotify"}
            </Button>
            {account?.connected && !confirming && (
              <Button variant="ghost" onClick={() => setConfirming(true)}>
                Disconnect
              </Button>
            )}
          </div>
        ) : (
          <p className={page.muted}>
            Spotify only lets GuildFM connect from the machine it runs on. Open{" "}
            <strong>{here}</strong> there, sign in, and connect from this page. For a machine
            without a screen, the README shows how to do it from a laptop.
          </p>
        )}

        {confirming && (
          <div className={spotify.confirm}>
            <span>Disconnect {account?.display_name}? Curators won't be able to import.</span>
            <span className={spotify.buttons}>
              <Button variant="secondary" onClick={() => setConfirming(false)}>
                Cancel
              </Button>
              <Button onClick={disconnect}>Disconnect</Button>
            </span>
          </div>
        )}
        <FormError message={error} />
      </div>
    </section>
  );
}
