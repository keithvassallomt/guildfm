import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type Handler = (data: Record<string, unknown>) => void;

type LiveValue = {
  connected: boolean;
  subscribe: (event: string, handler: Handler) => () => void;
};

const LiveContext = createContext<LiveValue | null>(null);

const PING_MS = 25_000;
const MAX_RETRY_MS = 15_000;

/** Keeps one websocket open to the server, reconnecting with backoff, and fans events out. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const [connected, setConnected] = useState(false);
  const handlers = useRef(new Map<string, Set<Handler>>());

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry: number | undefined;
    let ping: number | undefined;
    let attempts = 0;
    let stopped = false;

    const open = () => {
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${protocol}://${location.host}/ws`);
      socket.onopen = () => {
        attempts = 0;
        setConnected(true);
        ping = window.setInterval(() => socket?.send("ping"), PING_MS);
      };
      socket.onmessage = (message) => {
        const { event, data } = JSON.parse(message.data);
        handlers.current.get(event)?.forEach((handler) => handler(data));
      };
      socket.onclose = () => {
        setConnected(false);
        window.clearInterval(ping);
        if (stopped) return;
        attempts += 1;
        retry = window.setTimeout(open, Math.min(1000 * 2 ** attempts, MAX_RETRY_MS));
      };
    };

    open();
    return () => {
      stopped = true;
      window.clearTimeout(retry);
      window.clearInterval(ping);
      socket?.close();
    };
  }, []);

  const subscribe = useCallback((event: string, handler: Handler) => {
    const set = handlers.current.get(event) ?? new Set<Handler>();
    set.add(handler);
    handlers.current.set(event, set);
    return () => {
      set.delete(handler);
    };
  }, []);

  const value = useMemo(() => ({ connected, subscribe }), [connected, subscribe]);
  return <LiveContext value={value}>{children}</LiveContext>;
}

export function useLive(): LiveValue {
  const value = useContext(LiveContext);
  if (!value) throw new Error("useLive must be used inside LiveProvider");
  return value;
}

/** Runs `handler` whenever the server broadcasts `event`. */
export function useLiveEvent(event: string, handler: Handler) {
  const { subscribe } = useLive();
  const latest = useRef(handler);
  latest.current = handler;
  useEffect(() => subscribe(event, (data) => latest.current(data)), [event, subscribe]);
}
