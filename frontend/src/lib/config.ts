// Public, non-secret settings. HTTP calls go through Next's /api proxy; the WebSocket
// connects to the backend directly because the dev proxy does not carry WebSockets.
export const BACKEND_WS_URL = process.env.NEXT_PUBLIC_BACKEND_WS_URL ?? "ws://localhost:8000";
