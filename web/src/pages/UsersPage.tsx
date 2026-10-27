import { type FormEvent, useEffect, useId, useState } from "react";
import { Link } from "react-router";
import { api, errorText, type Role, type TemporaryPassword, type User } from "../api";
import { useMe } from "../auth/AuthProvider";
import { Avatar } from "../components/Avatar";
import { Button } from "../components/Button";
import { Dialog } from "../components/Dialog";
import { HelpLink } from "../components/HelpLink";
import { Icon } from "../components/Icon";
import { RoleBadge, roleOptions } from "../components/RoleBadge";
import { SegmentedControl } from "../components/SegmentedControl";
import { FormError, TextField } from "../components/TextField";
import styles from "./Page.module.css";
import users from "./UsersPage.module.css";

const byName = (a: User, b: User) => a.display_name.localeCompare(b.display_name);

export function UsersPage() {
  const me = useMe();
  const [list, setList] = useState<User[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    api<User[]>("GET", "/users")
      .then(setList)
      .catch((caught) => setError(errorText(caught)));
  }, []);

  const replace = (user: User) =>
    setList((current) => current?.map((u) => (u.id === user.id ? user : u)) ?? null);
  const add = (user: User) => setList((current) => [...(current ?? []), user].sort(byName));
  const remove = (id: number) => setList((current) => current?.filter((u) => u.id !== id) ?? null);

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerStart}>
          <Link to="/admin" aria-label="Back to Admin" className={styles.iconLink}>
            <Icon name="back" />
          </Link>
          <h1 className={styles.title}>Users</h1>
        </div>
        <div className={styles.headerEnd}>
          <Button onClick={() => setAdding(true)}>
            <Icon name="plus" size={16} strokeWidth={2.6} />
            Add
          </Button>
          <HelpLink />
        </div>
      </header>

      <FormError message={error} />
      {list && (
        <>
          <p className={styles.muted}>
            {list.length} {list.length === 1 ? "person" : "people"}. People can also sign
            themselves up.
          </p>
          <ul className={users.list}>
            {list.map((user) => (
              <UserRow
                key={user.id}
                user={user}
                isSelf={user.id === me.id}
                onChange={replace}
                onDeleted={remove}
              />
            ))}
          </ul>
        </>
      )}

      <AddUserDialog open={adding} onClose={() => setAdding(false)} onAdded={add} />
    </div>
  );
}

type RowProps = {
  user: User;
  isSelf: boolean;
  onChange: (user: User) => void;
  onDeleted: (id: number) => void;
};

type Confirming = "reset" | "delete" | null;

function UserRow({ user, isSelf, onChange, onDeleted }: RowProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<Confirming>(null);
  const [temporary, setTemporary] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const controlsId = useId();
  const name = user.display_name;

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  };

  const changeRole = (role: Role) =>
    role !== user.role &&
    run(async () => onChange(await api<User>("PATCH", `/users/${user.id}`, { role })));

  const reset = () =>
    run(async () => {
      const result = await api<TemporaryPassword>("POST", `/users/${user.id}/reset-password`);
      onChange(result.user);
      setTemporary(result.temporary_password);
      setConfirming(null);
    });

  const remove = () =>
    run(async () => {
      await api("DELETE", `/users/${user.id}`);
      onDeleted(user.id);
    });

  const ask = (what: Confirming) => {
    setConfirming(what);
    setTemporary(null);
    setError(null);
  };

  return (
    <li className={`${users.row} ${open ? users.open : ""}`}>
      <div className={users.summary}>
        <Avatar name={name} url={user.avatar_url} />
        <span className={users.who}>
          <span className={users.name}>{name}</span>
          <span className={users.handle}>
            @{user.username}
            {isSelf && " · you"}
          </span>
        </span>
        <RoleBadge role={user.role} />
        <button
          type="button"
          className={users.disclosure}
          aria-expanded={open}
          aria-controls={controlsId}
          aria-label={`Manage ${name}`}
          onClick={() => setOpen(!open)}
        >
          <Icon name="chevronDown" size={20} />
        </button>
      </div>

      <div id={controlsId} className={users.controls}>
        {isSelf ? (
          <p className={styles.muted}>This is you. Another admin would need to change your account.</p>
        ) : (
          <>
            <SegmentedControl
              label={`Role for ${name}`}
              options={roleOptions}
              value={user.role}
              onChange={changeRole}
              disabled={busy}
            />
            <span className={users.actions}>
              <Button variant="secondary" disabled={busy} onClick={() => ask("reset")}>
                Reset password
              </Button>
              <Button variant="secondary" disabled={busy} onClick={() => ask("delete")}>
                Delete
              </Button>
            </span>
          </>
        )}
      </div>

      {(confirming || temporary || error) && (
        <div className={users.extra}>
          {confirming && (
            <div className={users.confirm}>
              <span>
                {confirming === "reset"
                  ? `Reset ${name}'s password? They'll be signed out everywhere.`
                  : `Delete ${name}'s account? This can't be undone.`}
              </span>
              <span className={users.confirmButtons}>
                <Button variant="secondary" onClick={() => setConfirming(null)}>
                  Cancel
                </Button>
                <Button onClick={confirming === "reset" ? reset : remove} disabled={busy}>
                  {confirming === "reset" ? "Reset" : "Delete"}
                </Button>
              </span>
            </div>
          )}
          {temporary && <TemporaryPasswordBox name={name} password={temporary} />}
          <FormError message={error} />
        </div>
      )}
    </li>
  );
}

function TemporaryPasswordBox({ name, password }: { name: string; password: string }) {
  return (
    <div className={users.temporary}>
      <span className={styles.muted}>Temporary password for {name}</span>
      <span className={users.password}>{password}</span>
      <span className={users.hint}>
        Pass it on in person. They choose a new one when they sign in.
      </span>
    </div>
  );
}

type AddProps = { open: boolean; onClose: () => void; onAdded: (user: User) => void };

function AddUserDialog({ open, onClose, onAdded }: AddProps) {
  const [result, setResult] = useState<TemporaryPassword | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const close = () => {
    setResult(null);
    setError(null);
    onClose();
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const created = await api<TemporaryPassword>("POST", "/users", {
        display_name: String(form.get("display_name") ?? ""),
        username: String(form.get("username") ?? ""),
      });
      onAdded(created.user);
      setResult(created);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={close} title={result ? "Account created" : "Add someone"}>
      {result ? (
        <>
          <TemporaryPasswordBox name={result.user.display_name} password={result.temporary_password} />
          <Button block onClick={close}>
            Done
          </Button>
        </>
      ) : (
        <form className={users.form} onSubmit={submit}>
          <TextField label="Display name" name="display_name" required maxLength={40} autoComplete="off" />
          <TextField
            label="Username"
            name="username"
            required
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
          />
          <p className={styles.muted}>
            GuildFM makes a temporary password for you to pass on. New accounts start as users.
          </p>
          <FormError message={error} />
          <div className={users.formButtons}>
            <Button variant="secondary" onClick={close}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy}>
              Create account
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  );
}
