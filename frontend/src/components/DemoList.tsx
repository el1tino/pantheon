"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { RunInfo, listDemos } from "@/lib/api";

/** Recorded demo runs: anyone can watch them, no login needed. */
export default function DemoList({ className = "" }: { className?: string }) {
  const [demos, setDemos] = useState<RunInfo[]>([]);
  useEffect(() => {
    listDemos().then(setDemos).catch(() => {});
  }, []);
  if (!demos.length) return null;
  return (
    <section className={`w-full ${className}`}>
      <h2 className="mb-3 text-[15px] font-semibold text-white/85">Watch a demo</h2>
      <ul className="space-y-2">
        {demos.map((d) => (
          <li key={d.id}>
            <Link
              href={`/replay/${d.id}`}
              className="group flex items-center gap-3 glass rounded-2xl !border-amber-200/15 px-4 py-3 transition-colors hover:!border-amber-200/40"
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-amber-200/30 text-amber-100/90">
                <svg width="10" height="10" viewBox="0 0 12 12" fill="currentColor"><path d="M2.5 1.2v9.6c0 .5.5.8.9.5l7.4-4.8c.4-.3.4-.8 0-1L3.4.7c-.4-.3-.9 0-.9.5z" /></svg>
              </span>
              <span className="min-w-0 flex-1 truncate text-[13px] text-white/80 group-hover:text-white">{d.goal}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
