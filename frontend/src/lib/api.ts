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
