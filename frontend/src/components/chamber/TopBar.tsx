"use client";

import Link from "next/link";
import { APP_NAME } from "@/lib/app";
import { PHASES } from "@/lib/chamber/types";

type Props = {
  goal: string;
  phase: string;
  round: number | string | null;
  maxRounds: number;
  status: string;
  spent: number;
  cap: number;
};

const PHASE_LABEL: Record<string, string> = {
  convene: "Convene",
  ideas: "Ideas",
  research: "Research",
  roles: "Roles",
  build: "Build",
  integrate: "Integrate",
};

export function usd(v: number): string {
  return v >= 1 ? `$${v.toFixed(2)}` : `$${v.toFixed(4)}`;
}

function roundLabel(round: number | string | null, maxRounds: number, status: string): string {
  if (status === "done") return "Decided";
  if (status === "stopped") return "Stopped";
  if (status === "failed") return "Failed";
  if (status === "paused") return "Paused";
  if (round === "vote") return "Vote";
  if (typeof round === "number") return `Round ${round} of ${maxRounds}`;
  return "Summary";
}

export default function TopBar({ goal, phase, round, maxRounds, status, spent, cap }: Props) {
  const current = Math.max(0, PHASES.indexOf(phase as (typeof PHASES)[number]));
  const ratio = cap > 0 ? spent / cap : 0;
  const meterColour = ratio >= 1 ? "#f87171" : ratio >= 0.8 - 1e-9 ? "#F5A524" : "rgba(255,255,255,0.75)";
  return (
    <header className="relative z-30 flex h-14 shrink-0 items-center gap-6 border-b border-white/[0.06] bg-black/30 px-4 backdrop-blur md:px-6">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <Link href="/" className="shrink-0 text-[13px] font-semibold tracking-[0.18em] text-white/80 uppercase hover:text-white">
          {APP_NAME}
        </Link>
        <span className="hidden truncate text-[13px] text-white/45 md:block" title={goal}>
          {goal}
        </span>
      </div>

      <nav aria-label="Phases" className="hidden items-center gap-1 lg:flex">
        {PHASES.map((p, i) => {
          const active = i === current;
          const past = i < current;
          return (
            <div key={p} className="flex items-center gap-1">
              {i > 0 && <span className={`h-px w-6 ${past || active ? "bg-white/30" : "bg-white/10"}`} />}
              <div className="flex flex-col items-center">
                <span
                  className={`flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11.5px] tracking-wide ${
                    active ? "text-white" : past ? "text-white/55" : "text-white/25"
                  }`}
                  style={active ? { boxShadow: "0 0 18px rgba(255,220,170,0.25)", background: "rgba(255,255,255,0.06)" } : undefined}
                >
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${active ? "bg-amber-200" : past ? "bg-white/50" : "bg-white/15"}`}
                    style={active ? { boxShadow: "0 0 8px #fde68a" } : undefined}
                  />
                  {PHASE_LABEL[p]}
                </span>
              </div>
            </div>
          );
        })}
        <span className="ml-3 font-mono text-[11px] text-white/40">{roundLabel(round, maxRounds, status)}</span>
      </nav>

      <div className="flex flex-1 items-center justify-end gap-3" title="Spent against the budget cap">
        <span className="whitespace-nowrap font-mono text-[12px] tabular-nums" style={{ color: meterColour }}>
          {usd(spent)} <span className="text-white/30">/ {usd(cap)}</span>
        </span>
        <span className="relative hidden h-1.5 w-24 overflow-hidden rounded-full bg-white/10 sm:block md:w-32">
          <span
            className="absolute inset-y-0 left-0 rounded-full transition-[width,background-color] duration-700 ease-out"
            style={{ width: `${Math.min(100, ratio * 100)}%`, background: meterColour, boxShadow: `0 0 10px ${meterColour}` }}
          />
        </span>
      </div>
    </header>
  );
}
