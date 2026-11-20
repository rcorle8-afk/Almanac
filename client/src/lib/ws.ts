import { useCallback, useEffect, useRef, useState } from "react";
import type { ClientMessage, GameState, ServerMessage } from "./types";

const MIN_RETRY_MS = 500;
const MAX_RETRY_MS = 5000;

export interface Game {
  state: GameState | null;
  connected: boolean;
  error: string | null;
  // Add to Date.now() to get the server's clock.
  clockOffset: number;
  send: (message: ClientMessage) => void;
  // Drops the socket and opens a new one, which repeats `hello()`. Used after signing in,
  // because the server reads the session cookie when the socket opens.
  reconnect: () => void;
  // Set when another tab or device took this seat (or room); this socket stays closed.
  replaced: string | null;
  // The latest one-off message from the server (how a table invite went), with when it came.
  notice: { message: string; at: number } | null;
}

/** Keeps a socket open, sending `hello()` on every (re)connect. */
export function useGame(
  hello: () => ClientMessage,
  onMessage?: (message: ServerMessage, send: Game["send"]) => void,
): Game {
  const [state, setState] = useState<GameState | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clockOffset, setClockOffset] = useState(0);
  const [replaced, setReplaced] = useState<string | null>(null);
  const [notice, setNotice] = useState<Game["notice"]>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const retryMs = useRef(MIN_RETRY_MS);
  const callbacks = useRef({ hello, onMessage });
  callbacks.current = { hello, onMessage };

  const send = useCallback((message: ClientMessage) => {
    setError(null);
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify(message));
    } else {
      setError("Reconnecting. Try that again in a moment.");
    }
  }, []);

  const reconnect = useCallback(() => {
    retryMs.current = 0; // on purpose, so it reopens at once rather than after a backoff
    socketRef.current?.close();
  }, []);

  useEffect(() => {
    let stopped = false; // this page is going away
    let superseded = false; // the server handed the seat to another socket
    let retryTimer: number | undefined;

    function connect() {
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      const socket = new WebSocket(`${scheme}://${location.host}/ws`);
      socketRef.current = socket;

      socket.onopen = () => {
        retryMs.current = MIN_RETRY_MS;
        setConnected(true);
        socket.send(JSON.stringify(callbacks.current.hello()));
      };

      socket.onmessage = (event) => {
        const message: ServerMessage = JSON.parse(event.data);
        if (message.type === "state") {
          setState(message);
          setClockOffset(message.server_now - Date.now());
        } else if (message.type === "error") {
          setError(message.message);
          if (message.code === "replaced") {
            superseded = true;
            setReplaced(message.message);
          }
        } else if (message.type === "notice") {
          setNotice({ message: message.message, at: Date.now() });
        }
        callbacks.current.onMessage?.(message, send);
      };

      socket.onclose = () => {
        setConnected(false);
        if (stopped || superseded) return;
        retryTimer = window.setTimeout(connect, retryMs.current);
        retryMs.current = Math.min(Math.max(retryMs.current * 2, MIN_RETRY_MS), MAX_RETRY_MS);
      };
    }

    connect();
    return () => {
      stopped = true;
      window.clearTimeout(retryTimer);
      socketRef.current?.close();
    };
  }, [send]);

  return { state, connected, error, clockOffset, send, reconnect, replaced, notice };
}
