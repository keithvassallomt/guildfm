import { type FormEvent, useState } from "react";
import { errorText } from "../api";
import { useAuth } from "../auth/AuthProvider";
import { Button } from "../components/Button";
import { SegmentedControl } from "../components/SegmentedControl";
import { FormError, TextField } from "../components/TextField";
import styles from "./Gate.module.css";

type Mode = "signin" | "register";

export function WelcomePage() {
  const { signIn, register } = useAuth();
  const [mode, setMode] = useState<Mode>("signin");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const field = (name: string) => String(form.get(name) ?? "");
    setBusy(true);
    setError(null);
    try {
      if (mode === "signin") await signIn(field("username"), field("password"));
      else await register(field("username"), field("display_name"), field("password"));
    } catch (caught) {
      setError(errorText(caught));
      setBusy(false);
    }
  };

  return (
    <main className={styles.gate}>
      <div className={styles.panel}>
        <div className={styles.brand}>
          <svg width="56" height="56" viewBox="0 0 28 28" aria-hidden="true">
            <circle cx="14" cy="14" r="12" fill="none" stroke="currentColor" strokeWidth="1.6" />
            <path d="M14 14L20 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            <circle cx="14" cy="14" r="2.2" fill="currentColor" />
          </svg>
          <h1 className={styles.title}>GuildFM</h1>
          <p className={styles.tagline}>
            Pick what plays in the office. Request songs, vote on the queue, and hear your name
            on air.
          </p>
        </div>

        <SegmentedControl
          label="Account"
          options={[
            { value: "signin", label: "Sign in" },
            { value: "register", label: "Create account" },
          ]}
          value={mode}
          onChange={(next) => {
            setMode(next);
            setError(null);
          }}
        />

        <form key={mode} className={styles.form} onSubmit={submit}>
          {mode === "register" && (
            <TextField
              label="Display name"
              name="display_name"
              required
              maxLength={40}
              autoComplete="nickname"
              hint="The DJ reads this out when it announces your requests."
            />
          )}
          <TextField
            label="Username"
            name="username"
            required
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            hint={mode === "register" ? "Letters, numbers, dots, dashes or underscores." : undefined}
          />
          <TextField
            label="Password"
            name="password"
            type="password"
            required
            autoComplete={mode === "signin" ? "current-password" : "new-password"}
            hint={mode === "register" ? "At least 8 characters." : undefined}
          />
          <FormError message={error} />
          <Button type="submit" block disabled={busy}>
            {mode === "signin" ? "Sign in" : "Create account"}
          </Button>
          {mode === "signin" && (
            <p className={styles.note}>Forgot your password? Ask an admin to reset it.</p>
          )}
        </form>
      </div>
    </main>
  );
}
