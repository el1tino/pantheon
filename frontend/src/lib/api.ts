// All model traffic goes through the backend. The browser never holds a key.
// Requests to /api/* are proxied to the backend by next.config.ts.

export type TestCallResult = {
  run_id: string;
  model: string;
  reply: string;
  tokens: number;
  cost_usd: number | null;
};

export async function testCall(prompt: string): Promise<TestCallResult> {
  const res = await fetch("/api/test-call", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  if (res.status === 401) goToLogin();
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export type SeatOption = {
  letter: string;
  name: string;
  provider: string;
  colour: string;
  logo?: string;
  model_id: string;
};

export type RunSummary = {
  id: string;
  goal: string;
  status: string;
  phase: string;
  budget_usd: number;
  spent_usd: number;
  created_at: string;
};

export type RunInfo = RunSummary & { public: boolean; site_key: string; can_change: boolean; live: boolean };

export type User = { id: string; email: string; is_owner: boolean };

export type StoredEvent = { seq: number; type: string; payload: Record<string, unknown>; at: number };

export const publicConfig = () => request<{ app_name: string; demo_mode: boolean }>("/api/config/public");
export const me = () => request<User>("/api/auth/me", { quiet401: true });
export const login = (email: string, password: string) =>
  request<User>("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }), quiet401: true });
export const logout = () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" });
export const createInvite = () => request<{ code: string; path: string; expires_at: string }>("/api/invites", { method: "POST" });
export const checkInvite = (code: string) => request<{ valid: boolean }>(`/api/invites/${encodeURIComponent(code)}`);
export const acceptInvite = (code: string, email: string, password: string) =>
  request<User>(`/api/invites/${encodeURIComponent(code)}/accept`, {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

export const getRun = (runId: string) => request<RunInfo>(`/api/runs/${runId}`);
export const runEvents = (runId: string) => request<StoredEvent[]>(`/api/runs/${runId}/events`);
export const listDemos = () => request<RunInfo[]>("/api/demos");

/** Sends the browser to the login page, coming back here afterwards. */
export function goToLogin() {
  if (typeof window === "undefined" || window.location.pathname.startsWith("/login")) return;
  const next = window.location.pathname + window.location.search;
  window.location.assign(`/login?next=${encodeURIComponent(next)}`);
}

export class HttpError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type RequestOptions = RequestInit & { quiet401?: boolean };

async function request<T>(path: string, init?: RequestOptions): Promise<T> {
  const { quiet401, ...rest } = init ?? {};
  const res = await fetch(path, {
    ...rest,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(rest.headers ?? {}) },
  });
  if (res.status === 401 && !quiet401) goToLogin();
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {}
    throw new HttpError(res.status, detail);
  }
  return res.json();
}

export const listSeats = () => request<SeatOption[]>("/api/seats");
export const listRuns = () => request<RunSummary[]>("/api/runs");

export const createRun = (body: {
  goal: string;
  seats: string[];
  budget_usd: number;
  max_rounds: number;
  cheap: boolean;
  mission: string;
}) => request<{ run_id: string }>("/api/runs", { method: "POST", body: JSON.stringify(body) });

export const controlRun = (runId: string, action: "pause" | "resume" | "stop") =>
  request<{ ok: boolean }>(`/api/runs/${runId}/control`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });

export const answerBudget = (runId: string, action: "raise" | "stop", cap_usd?: number) =>
  request<{ ok: boolean }>(`/api/runs/${runId}/budget`, {
    method: "POST",
    body: JSON.stringify({ action, cap_usd }),
  });

export type MissionOption = { key: string; label: string; tagline: string; available: boolean };

export const listMissions = () => request<MissionOption[]>("/api/missions");

export const answerCheckpoint = (
  runId: string,
  answer: { action: string; option?: string; note?: string; assignments?: Record<string, { owner: string; reviewer: string }> },
) =>
  request<{ ok: boolean }>(`/api/runs/${runId}/checkpoint`, { method: "POST", body: JSON.stringify(answer) });

export const sendMessage = (runId: string, text: string) =>
  request<{ id: string }>(`/api/runs/${runId}/message`, { method: "POST", body: JSON.stringify({ text }) });

export type TreeFile = { path: string; size: number };

export const runTree = (runId: string) => request<TreeFile[]>(`/api/runs/${runId}/tree`);

export async function fileText(runId: string, path: string): Promise<string> {
  const res = await fetch(`/api/runs/${runId}/files/${path}?inline=true`, { credentials: "same-origin" });
  if (res.status === 401) goToLogin();
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.text();
}

/**
 * The built site is served by the backend with a strict CSP; the iframe is sandboxed too.
 * The sandboxed frame has an opaque origin and sends no login cookie, so sites live at a
 * hard-to-guess per-run key instead of behind the login.
 */
export const siteUrl = (siteKey: string, path = "index.html", version: number | string = 0, bust: number = 0) =>
  `/api/sites/${siteKey}/${path}?v=${version}${bust ? `-${bust}` : ""}`;
