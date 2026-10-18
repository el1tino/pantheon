"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { usd } from "./TopBar";
import { GROUP_NAME } from "@/lib/app";

type Props = {
  spent: number;
  cap: number;
  estimate: number;
  onRaise: (cap: number) => Promise<void>;
  onStop: () => Promise<void>;
};

/** Shown when the next call would pass the budget cap. The run waits for an answer. */
export default function BudgetCard({ spent, cap, estimate, onRaise, onStop }: Props) {
  const [value, setValue] = useState(() => {
    const suggested = Math.max(cap * 2, spent + estimate * 4);
    return suggested >= 1 ? suggested.toFixed(2) : suggested.toFixed(4); // tiny dev caps stay non-zero
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const act = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };
  const newCap = Number(value);
  return (
    <div className="glass-scrim absolute inset-0 z-50 flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, y: 24, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
        className="glass-thick w-[min(420px,92vw)] rounded-[22px] !border-red-400/25 p-6"
        style={{ boxShadow: "0 0 60px rgba(248,113,113,0.12)" }}
      >
        <div className="mb-1 text-[10px] uppercase tracking-[0.3em] text-red-300/80">Budget cap reached</div>
        <h2 className="mb-3 text-lg font-medium text-white">The {GROUP_NAME} has paused.</h2>
        <p className="mb-5 text-[13px] leading-relaxed text-white/60">
          It has spent <span className="font-mono text-white/85">{usd(spent)}</span> of{" "}
          <span className="font-mono text-white/85">{usd(cap)}</span>. The next call is estimated at{" "}
          <span className="font-mono text-white/85">{usd(estimate)}</span>. Raise the cap to continue, or stop here.
        </p>
        <label className="mb-4 flex items-center gap-2 text-[13px] text-white/60">
          New cap
          <span className="glass-well flex items-center rounded-xl px-2">
            <span className="text-white/40">$</span>
            <input
              type="number"
              min={0}
              step="any"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="w-24 bg-transparent px-1 py-1.5 font-mono text-white outline-none"
            />
          </span>
        </label>
        {error && <p className="mb-3 text-[12px] text-red-300">{error}</p>}
        <div className="flex gap-2">
          <button
            disabled={busy || !(newCap > cap)}
            onClick={() => act(() => onRaise(newCap))}
            className="flex-1 accent-button rounded-full px-3 py-2 text-[13px] font-medium disabled:opacity-40"
          >
            Raise cap and continue
          </button>
          <button
            disabled={busy}
            onClick={() => act(onStop)}
            className="glass-button rounded-full px-3 py-2 text-[13px] text-white/80 disabled:opacity-40"
          >
            Stop run
          </button>
        </div>
      </motion.div>
    </div>
  );
}
