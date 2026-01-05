---
status: active
started: 2026-01-03
---

# Task: WebSocket Reconnection on Mobile

## Issue

When leaving mobile browser (app still plays in background from buffer), WebSocket eventually drops. Shows "connection lost" error but doesn't reconnect without page refresh.

Should either reconnect automatically, or show better error with refresh action.

## Files

- `frontend/src/hooks/useTTSWebSocket.ts`
