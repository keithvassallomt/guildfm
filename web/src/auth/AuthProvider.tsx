import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { ApiError, api, type Me, type Permission } from "../api";

type ProfileChanges = Partial<Pick<Me, "display_name" | "announce_requests">>;

type AuthValue = {
  /** Undefined while the first check is still running. */
  me: Me | null | undefined;
  can: (permission: Permission) => boolean;
  refresh: () => Promise<void>;
  signIn: (username: string, password: string) => Promise<void>;
  register: (username: string, displayName: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  choosePassword: (password: string) => Promise<void>;
  updateProfile: (changes: ProfileChanges) => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      setMe(await api<Me>("GET", "/me"));
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) setMe(null);
      else throw error;
    }
  }, []);

  useEffect(() => {
    refresh().catch(() => setMe(null));
    // Pick up role changes or a password reset when someone comes back to the tab.
    const onVisible = () => {
      if (document.visibilityState === "visible") refresh().catch(() => {});
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [refresh]);

  const value = useMemo<AuthValue>(
    () => ({
      me,
      can: (permission) => !!me?.permissions.includes(permission),
      refresh,
      signIn: async (username, password) => {
        setMe(await api<Me>("POST", "/auth/login", { username, password }));
      },
      register: async (username, displayName, password) => {
        setMe(
          await api<Me>("POST", "/auth/register", {
            username,
            display_name: displayName,
            password,
          }),
        );
      },
      signOut: async () => {
        await api("POST", "/auth/logout");
        setMe(null);
      },
      choosePassword: async (password) => {
        setMe(await api<Me>("POST", "/me/password", { password }));
      },
      updateProfile: async (changes) => {
        setMe(await api<Me>("PATCH", "/me", changes));
      },
    }),
    [me, refresh],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

/** For screens that only render once someone is signed in. */
export function useMe(): Me {
  const { me } = useAuth();
  if (!me) throw new Error("useMe needs a signed-in user");
  return me;
}
