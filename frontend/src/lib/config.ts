// Public, non-secret settings. HTTP calls go through Next's /api proxy. The WebSocket goes
// to the same host as the page (a reverse proxy such as Caddy routes /api to the backend),
// except in development, where the page is on :3000 and the backend is on :8000.
export function backendWsUrl(): string {
  const fixed = process.env.NEXT_PUBLIC_BACKEND_WS_URL;
  if (fixed) return fixed;
  if (typeof window === "undefined") return "ws://localhost:8000";
  const { protocol, hostname, host, port } = window.location;
  const scheme = protocol === "https:" ? "wss:" : "ws:";
  return port === "3000" ? `${scheme}//${hostname}:8000` : `${scheme}//${host}`;
}
