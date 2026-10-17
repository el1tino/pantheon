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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
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

export const listSeats = () => request<SeatOption[]>("/api/seats");
export const listRuns = () => request<RunSummary[]>("/api/runs");

export const createRun = (body: {
  goal: string;
  seats: string[];
  budget_usd: number;
  max_rounds: number;
  cheap: boolean;
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
