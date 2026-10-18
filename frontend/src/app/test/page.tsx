"use client";

import { useState } from "react";
import Link from "next/link";
import { THE_GROUP } from "@/lib/app";
import { testCall, type TestCallResult } from "@/lib/api";

export default function TestPage() {
  const [prompt, setPrompt] = useState(`Introduce yourself to ${THE_GROUP} in one sentence.`);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<TestCallResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await testCall(prompt));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-6 px-6 py-16">
      <header className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Test call</h1>
        <Link href="/" className="text-sm text-muted hover:text-foreground">
          Home
        </Link>
      </header>

      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
          className="glass-well w-full resize-y rounded-xl p-3 outline-none"
        />
        <button
          type="submit"
          disabled={loading || !prompt.trim()}
          className="self-start accent-button rounded-full px-4 py-2 text-sm font-medium transition-opacity disabled:opacity-40"
        >
          {loading ? "Waiting for the model…" : "Send"}
        </button>
      </form>

      {error && (
        <div className="rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {result && (
        <section className="glass flex flex-col gap-3 rounded-2xl p-4">
          <p className="whitespace-pre-wrap leading-relaxed">{result.reply}</p>
          <dl className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted">
            <div>model <span className="text-foreground">{result.model}</span></div>
            <div>tokens <span className="text-foreground">{result.tokens}</span></div>
            <div>
              cost{" "}
              <span className="text-foreground">
                {result.cost_usd == null ? "n/a" : `$${result.cost_usd.toFixed(6)}`}
              </span>
            </div>
            <div>run <span className="text-foreground">{result.run_id}</span></div>
          </dl>
        </section>
      )}
    </main>
  );
}
