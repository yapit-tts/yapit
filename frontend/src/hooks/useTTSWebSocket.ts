import { useCallback, useEffect, useRef, useState } from "react";
import { useUser } from "@stackframe/react";
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
): UseTTSWebSocketReturn {
  const user = useUser();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;
  const onConnectRef = useRef(onConnect);
  onConnectRef.current = onConnect;

  const MAX_RECONNECT_ATTEMPTS = 5;
  const BASE_RECONNECT_DELAY = 1000;

  const [isConnected, setIsConnected] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const isConnectedRef = useRef(false);

  // Message queue: messages sent while WS is not connected are queued and drained on connect
  const messageQueueRef = useRef<object[]>([]);

  const getWebSocketUrl = useCallback(async (): Promise<string> => {
    const baseUrl = `${WS_BASE_URL}/v1/ws/tts`;
    if (user?.currentSession) {
      try {
        const { accessToken } = await user.currentSession.getTokens();
        if (accessToken) {
          return `${baseUrl}?token=${encodeURIComponent(accessToken)}`;
        }
      } catch (err) {
        console.error("[TTS WS] Failed to get access token:", err);
      }
    }
    const anonymousId = await getOrCreateAnonymousId();
    const anonymousToken = getAnonymousToken();
    return `${baseUrl}?anonymous_id=${encodeURIComponent(anonymousId)}&anonymous_token=${encodeURIComponent(anonymousToken ?? "")}`;
  }, [user]);

  const connect = useCallback(async () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const url = await getWebSocketUrl();
      console.log("[TTS WS] Connecting to:", url.replace(/token=[^&]+/, "token=***"));
      const ws = new WebSocket(url);

      ws.onopen = () => {
        wsRef.current = ws;
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

        reconnectAttemptsRef.current = 0;
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
        console.log("[TTS WS] Disconnected:", event.code, event.reason);
        isConnectedRef.current = false;
        setIsConnected(false);
        wsRef.current = null;

        if (event.code !== 1000 && event.code !== 1008) {
          if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
            setIsReconnecting(true);
            const delay = BASE_RECONNECT_DELAY * Math.pow(2, reconnectAttemptsRef.current);
            console.log(`[TTS WS] Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current + 1})`);
            reconnectTimeoutRef.current = window.setTimeout(() => {
              reconnectAttemptsRef.current++;
              connect();
            }, delay);
          } else {
            setIsReconnecting(false);
            setConnectionError("Connection lost. Please refresh the page.");
          }
        } else if (event.code === 1008) {
          setIsReconnecting(false);
          setConnectionError("Authentication failed. Please log in again.");
        }
      };
    } catch (err) {
      console.error("[TTS WS] Failed to connect:", err);
      setConnectionError("Failed to connect to server");
    }
  }, [getWebSocketUrl]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) {
        wsRef.current.close(1000);
        wsRef.current = null;
      }
      isConnectedRef.current = false;
      setIsConnected(false);
    };
  }, [connect]);

  const send = useCallback((msg: object) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      messageQueueRef.current.push(msg);
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
