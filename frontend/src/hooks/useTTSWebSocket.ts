import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useUser } from "@stackframe/react";
import { getOrCreateAnonymousId } from "@/lib/anonymousId";

const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL;

export type BlockStatus = "pending" | "queued" | "processing" | "cached" | "skipped" | "error";

interface WSBlockStatusMessage {
  type: "status";
  document_id: string;
  block_idx: number;
  status: "queued" | "processing" | "cached" | "skipped" | "error";
  audio_url?: string;
  error?: string;
}

interface WSEvictedMessage {
  type: "evicted";
  document_id: string;
  block_indices: number[];
}

interface WSErrorMessage {
  type: "error";
  error: string;
}

type WSMessage = WSBlockStatusMessage | WSEvictedMessage | WSErrorMessage;

interface SynthesizeParams {
  documentId: string;
  blockIndices: number[];
  model: string;
  voice: string;
  cursor: number;
}

export interface UseTTSWebSocketReturn {
  isConnected: boolean;
  isReconnecting: boolean;
  connectionError: string | null;
  blockStates: Map<number, BlockStatus>;
  audioUrls: Map<number, string>;
  synthesize: (params: SynthesizeParams) => void;
  moveCursor: (documentId: string, cursor: number) => void;
  reset: () => void;
  checkConnected: () => boolean;
  getAudioUrl: (blockIdx: number) => string | undefined;
  getBlockStatus: (blockIdx: number) => BlockStatus | undefined;
}

export function useTTSWebSocket(): UseTTSWebSocketReturn {
  const user = useUser();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const MAX_RECONNECT_ATTEMPTS = 5;
  const BASE_RECONNECT_DELAY = 1000;

  const [isConnected, setIsConnected] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [blockStates, setBlockStates] = useState<Map<number, BlockStatus>>(new Map());
  const [audioUrls, setAudioUrls] = useState<Map<number, string>>(new Map());

  // Refs for accessing current values in async code (avoids stale closure issues)
  const isConnectedRef = useRef(false);
  const blockStatesRef = useRef<Map<number, BlockStatus>>(new Map());
  const audioUrlsRef = useRef<Map<number, string>>(new Map());

  // Build WS URL with auth query params
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

    // Fall back to anonymous ID
    const anonymousId = getOrCreateAnonymousId();
    return `${baseUrl}?anonymous_id=${encodeURIComponent(anonymousId)}`;
  }, [user]);

  // Handle incoming WS messages
  const handleMessage = useCallback((event: MessageEvent) => {
    try {
      const data: WSMessage = JSON.parse(event.data);

      if (data.type === "status") {
        const msg = data as WSBlockStatusMessage;
        console.log(`[TTS WS] Block ${msg.block_idx} status: ${msg.status}${msg.audio_url ? ` (url: ${msg.audio_url})` : ''}`);
        blockStatesRef.current.set(msg.block_idx, msg.status);
        setBlockStates((prev) => {
          const next = new Map(prev);
          next.set(msg.block_idx, msg.status);
          return next;
        });

        if (msg.audio_url && msg.status === "cached") {
          audioUrlsRef.current.set(msg.block_idx, msg.audio_url);
          setAudioUrls((prev) => {
            const next = new Map(prev);
            next.set(msg.block_idx, msg.audio_url!);
            return next;
          });
        }
      } else if (data.type === "evicted") {
        const msg = data as WSEvictedMessage;
        for (const idx of msg.block_indices) {
          blockStatesRef.current.delete(idx);
          audioUrlsRef.current.delete(idx);
        }
        setBlockStates((prev) => {
          const next = new Map(prev);
          for (const idx of msg.block_indices) {
            next.delete(idx);
          }
          return next;
        });
        setAudioUrls((prev) => {
          const next = new Map(prev);
          for (const idx of msg.block_indices) {
            next.delete(idx);
          }
          return next;
        });
      } else if (data.type === "error") {
        console.error("[TTS WS] Server error:", data.error);
        setConnectionError(data.error);
      }
    } catch (err) {
      console.error("[TTS WS] Failed to parse message:", err);
    }
  }, []);

  // Connect to WebSocket
  const connect = useCallback(async () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    try {
      const url = await getWebSocketUrl();
      console.log("[TTS WS] Connecting to:", url.replace(/token=[^&]+/, "token=***"));

      const ws = new WebSocket(url);

      ws.onopen = () => {
        // Only set wsRef on successful open, so cleanup only closes open connections
        // This handles race conditions with auth changes causing multiple connect() calls
        wsRef.current = ws;
        console.log("[TTS WS] Connected");
        isConnectedRef.current = true;
        setIsConnected(true);
        setIsReconnecting(false);
        setConnectionError(null);

        // Clear stale queued/processing states from before disconnect
        // Keep 'cached' since we already fetched that audio locally
        const staleIndices: number[] = [];
        blockStatesRef.current.forEach((status, idx) => {
          if (status === 'queued' || status === 'processing') {
            staleIndices.push(idx);
          }
        });
        if (staleIndices.length > 0) {
          console.log(`[TTS WS] Clearing ${staleIndices.length} stale block states after reconnect`);
          for (const idx of staleIndices) {
            blockStatesRef.current.delete(idx);
          }
          setBlockStates((prev) => {
            const next = new Map(prev);
            for (const idx of staleIndices) {
              next.delete(idx);
            }
            return next;
          });
        }

        reconnectAttemptsRef.current = 0;
      };

      ws.onmessage = handleMessage;

      ws.onerror = (event) => {
        console.error("[TTS WS] Error:", event);
      };

      ws.onclose = (event) => {
        console.log("[TTS WS] Disconnected:", event.code, event.reason);
        isConnectedRef.current = false;
        setIsConnected(false);
        wsRef.current = null;

        // Auto-reconnect unless closed intentionally (1000) or auth failed (1008)
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
  }, [getWebSocketUrl, handleMessage]);

  // Connect on mount, reconnect when auth changes, disconnect on unmount
  // Note: When user?.id changes, `getWebSocketUrl` changes → `connect` changes →
  // this effect re-runs. The cleanup closes the old WS, then connect() creates a new one.
  // This avoids the race condition of having a separate auth effect.
  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close(1000);
        wsRef.current = null;
      }
      // Keep refs and state in sync (important for StrictMode double-invoke)
      isConnectedRef.current = false;
      setIsConnected(false);
    };
  }, [connect]);

  // Send synthesize request
  const synthesize = useCallback((params: SynthesizeParams) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.warn("[TTS WS] Cannot synthesize: not connected");
      return;
    }

    // Mark blocks as queued immediately (clears any previous error state)
    for (const idx of params.blockIndices) {
      blockStatesRef.current.set(idx, 'queued');
    }

    const message = {
      type: "synthesize",
      document_id: params.documentId,
      block_indices: params.blockIndices,
      cursor: params.cursor,
      model: params.model,
      voice: params.voice,
      synthesis_mode: "server",
    };

    console.log(`[TTS WS] Requesting synthesis for blocks: ${params.blockIndices.join(", ")}`);
    wsRef.current.send(JSON.stringify(message));
  }, []);

  // Send cursor moved message
  const moveCursor = useCallback((documentId: string, cursor: number) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      return;
    }

    const message = {
      type: "cursor_moved",
      document_id: documentId,
      cursor,
    };

    wsRef.current.send(JSON.stringify(message));
  }, []);

  const reset = useCallback(() => {
    blockStatesRef.current = new Map();
    audioUrlsRef.current = new Map();
    setBlockStates(new Map());
    setAudioUrls(new Map());
  }, []);

  const checkConnected = useCallback(() => {
    // Use ref instead of checking wsRef.current.readyState directly
    // This avoids issues with async connection and StrictMode
    return isConnectedRef.current;
  }, []);

  const getAudioUrl = useCallback((blockIdx: number) => {
    return audioUrlsRef.current.get(blockIdx);
  }, []);

  const getBlockStatus = useCallback((blockIdx: number) => {
    return blockStatesRef.current.get(blockIdx);
  }, []);

  return useMemo(() => ({
    isConnected,
    isReconnecting,
    connectionError,
    blockStates,
    audioUrls,
    synthesize,
    moveCursor,
    reset,
    checkConnected,
    getAudioUrl,
    getBlockStatus,
  }), [
    isConnected,
    isReconnecting,
    connectionError,
    blockStates,
    audioUrls,
    synthesize,
    moveCursor,
    reset,
    checkConnected,
    getAudioUrl,
    getBlockStatus,
  ]);
}
