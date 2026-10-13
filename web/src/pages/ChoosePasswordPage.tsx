import { type FormEvent, useState } from "react";
import { errorText } from "../api";
import { useAuth } from "../auth/AuthProvider";
import { Button } from "../components/Button";
import { FormError, TextField } from "../components/TextField";
import styles from "./Gate.module.css";

/** Shown after signing in with a temporary password, until you pick your own. */
export function ChoosePasswordPage() {
  const { choosePassword, signOut } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") ?? "");
    if (password !== form.get("confirm")) {
      setError("Those passwords don't match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await choosePassword(password);
    } catch (caught) {
      setError(errorText(caught));
      setBusy(false);
    }
  };

  return (
    <main className={styles.gate}>
      <div className={styles.panel}>
        <div className={styles.brand}>
          <h1 className={styles.heading}>Choose a new password</h1>
          <p className={styles.tagline}>
            You signed in with a temporary password. Pick your own to carry on.
          </p>
        </div>
        <form className={styles.form} onSubmit={submit}>
          <TextField
            label="New password"
            name="password"
            type="password"
            required
            autoComplete="new-password"
            hint="At least 8 characters."
          />
          <TextField
            label="Type it again"
            name="confirm"
            type="password"
            required
            autoComplete="new-password"
          />
          <FormError message={error} />
          <Button type="submit" block disabled={busy}>
            Save password
          </Button>
          <Button variant="ghost" onClick={() => signOut()}>
            Sign out instead
          </Button>
        </form>
      </div>
    </main>
  );
}
