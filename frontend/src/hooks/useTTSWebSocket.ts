import { useCallback, useEffect, useRef, useState } from "react";
import { useAuthUser } from "@/hooks/useAuthUser";
import { authEnabled } from "@/auth";
import { getAnonymousToken, getOrCreateAnonymousId } from "@/lib/anonymousId";

const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL ||
	`${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/api`;

export interface WSMessage {
  type: "status" | "evicted" | "error";
  [key: string]: unknown;
}

export interface UseTTSWebSocketReturn {
  isConnected: boolean;
  isReconnecting: boolean;
  connectionError: string | null;
  send: (msg: object) => void;
  checkConnected: () => boolean;
}

export function useTTSWebSocket(
  onMessage: (data: WSMessage) => void,
  onConnect?: () => void,
  isPlaybackActive?: () => boolean,
): UseTTSWebSocketReturn {
  const user = useAuthUser();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;
  const onConnectRef = useRef(onConnect);
  onConnectRef.current = onConnect;
  const isPlaybackActiveRef = useRef(isPlaybackActive);
  isPlaybackActiveRef.current = isPlaybackActive;

  const BASE_RECONNECT_DELAY = 1000;
  const MAX_RECONNECT_DELAY = 30000;
  const MAX_AUTH_FAILURES = 3;
  // The gateway pings at 20s and drops the socket 20s later if no pong arrives (uvicorn
  // defaults), so a connection has to outlive one full cycle before it counts as working.
  const STABLE_CONNECTION_MS = 60000;

  const [isConnected, setIsConnected] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const isConnectedRef = useRef(false);
  const connectingRef = useRef(false);
  const epochRef = useRef(0);
  const authFailuresRef = useRef(0);
  const openedAtRef = useRef(0);

  // Message queue: messages sent while WS is not connected are queued and drained on connect
  const messageQueueRef = useRef<object[]>([]);

  const getWebSocketUrl = useCallback(async (): Promise<string> => {
    const baseUrl = `${WS_BASE_URL}/v1/ws/tts`;
    if (!authEnabled) return baseUrl;
    if (user?.currentSession) {
      // getTokens() refreshes the access token via the refresh token when expired.
      // A failure here is transient (e.g. mobile network after backgrounding) — throw
      // so connect() retries. Never downgrade a signed-in user to an anonymous identity.
      const { accessToken } = await user.currentSession.getTokens();
      if (!accessToken) throw new Error("No access token for signed-in session");
      return `${baseUrl}?token=${encodeURIComponent(accessToken)}`;
    }
    const anonymousId = await getOrCreateAnonymousId();
    const anonymousToken = getAnonymousToken();
    return `${baseUrl}?anonymous_id=${encodeURIComponent(anonymousId)}&anonymous_token=${encodeURIComponent(anonymousToken ?? "")}`;
  }, [user]);

  const connect = useCallback(async () => {
    // wsRef is set at creation, so non-null covers CONNECTING and OPEN;
    // connectingRef covers the async token fetch before the socket exists.
    if (connectingRef.current || wsRef.current) return;
    connectingRef.current = true;
    const epoch = epochRef.current;

    const scheduleReconnect = () => {
      // A hidden tab with nothing playing needs no socket, and the gateway will keep
      // dropping it as unresponsive once the tab is throttled — reconnecting is a loop
      // that never ends. wake() below reconnects the moment the tab is visible again.
      // Hidden *and* playing is background listening, which must stay connected.
      if (document.visibilityState === "hidden" && !isPlaybackActiveRef.current?.()) {
        setIsReconnecting(false);
        return;
      }
      setIsReconnecting(true);
      const delay = Math.min(BASE_RECONNECT_DELAY * Math.pow(2, reconnectAttemptsRef.current), MAX_RECONNECT_DELAY);
      console.log(`[TTS WS] Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current + 1})`);
      reconnectTimeoutRef.current = window.setTimeout(() => {
        reconnectAttemptsRef.current++;
        connect();
      }, delay);
    };

    try {
      const url = await getWebSocketUrl();
      if (epoch !== epochRef.current) {
        // Unmounted or user changed while fetching the token — abandon this attempt
        connectingRef.current = false;
        return;
      }
      console.log("[TTS WS] Connecting to:", url.replace(/token=[^&]+/, "token=***"));
      openedAtRef.current = 0;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        connectingRef.current = false;
        openedAtRef.current = Date.now();
        console.log("[TTS WS] Connected");
        isConnectedRef.current = true;
        setIsConnected(true);
        setIsReconnecting(false);
        setConnectionError(null);

        // Drain queued messages
        const queue = messageQueueRef.current;
        if (queue.length > 0) {
          console.log(`[TTS WS] Draining ${queue.length} queued messages`);
          for (const msg of queue) {
            ws.send(JSON.stringify(msg));
          }
          messageQueueRef.current = [];
        }

        // Notify listeners (synthesizer uses this to retry pending blocks)
        onConnectRef.current?.();

        authFailuresRef.current = 0;
      };

      ws.onmessage = (event: MessageEvent) => {
        try {
          const data: WSMessage = JSON.parse(event.data);
          onMessageRef.current(data);
        } catch (err) {
          console.error("[TTS WS] Failed to parse message:", err);
        }
      };

      ws.onerror = (event) => {
        console.error("[TTS WS] Error:", event);
      };

      ws.onclose = (event) => {
        connectingRef.current = false;
        console.log("[TTS WS] Disconnected:", event.code, event.reason);
        isConnectedRef.current = false;
        setIsConnected(false);
        if (wsRef.current === ws) wsRef.current = null;

        // Reset backoff only for a socket that actually held. Resetting on open instead
        // means a peer that connects and dies every cycle never backs off at all.
        if (openedAtRef.current && Date.now() - openedAtRef.current >= STABLE_CONNECTION_MS) {
          reconnectAttemptsRef.current = 0;
        }

        if (event.code === 1000) return;

        if (event.code === 1008) {
          // Auth rejection is usually a stale access token — each reconnect fetches a
          // fresh one via getTokens(). Only give up after repeated failures (dead session).
          authFailuresRef.current++;
          if (authFailuresRef.current >= MAX_AUTH_FAILURES) {
            setIsReconnecting(false);
            setConnectionError("Authentication failed. Please log in again.");
            return;
          }
        }

        scheduleReconnect();
      };
    } catch (err) {
      connectingRef.current = false;
      console.error("[TTS WS] Failed to connect:", err);
      scheduleReconnect();
    }
  }, [getWebSocketUrl]);

  const connectRef = useRef(connect);
  connectRef.current = connect;

  useEffect(() => {
    connect();
    return () => {
      epochRef.current++;
      connectingRef.current = false;
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) {
        wsRef.current.close(1000);
        wsRef.current = null;
      }
      isConnectedRef.current = false;
      setIsConnected(false);
    };
  }, [connect]);

  // Mobile resume: when the app returns to the foreground (or network comes back),
  // the backoff timer may be up to 30s out — or we gave up after auth failures.
  // Reset and reconnect immediately so pause→play after unlock is seamless.
  useEffect(() => {
    const wake = () => {
      if (connectingRef.current || wsRef.current) return;
      reconnectAttemptsRef.current = 0;
      authFailuresRef.current = 0;
      setConnectionError(null);
      setIsReconnecting(false);
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      connect();
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") wake();
    };
    window.addEventListener("online", wake);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("online", wake);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [connect]);

  const send = useCallback((msg: object) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      messageQueueRef.current.push(msg);
      // scheduleReconnect leaves a hidden, idle tab disconnected. A queued message means
      // the socket is wanted again, so reopen here — onopen drains the queue.
      if (!wsRef.current && !connectingRef.current) {
        reconnectAttemptsRef.current = 0;
        connectRef.current();
      }
      return;
    }
    wsRef.current.send(JSON.stringify(msg));
  }, []);

  const checkConnected = useCallback(() => isConnectedRef.current, []);

  return {
    isConnected,
    isReconnecting,
    connectionError,
    send,
    checkConnected,
  };
}
