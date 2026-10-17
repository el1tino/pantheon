"use client";

import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { SeatView } from "@/lib/chamber/reducer";
import { Diff, MODERATOR } from "@/lib/chamber/types";

type Props = { diffs: Diff[]; seats: SeatView[]; onClose: () => void };

/** Git-style feed of every change, tagged with the seat that made it. */
export default function DiffFeed({ diffs, seats, onClose }: Props) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView({ behavior: "smooth" }), [diffs.length]);
  const colourOf = (l: string) => (l === MODERATOR ? "#ffffff" : seats.find((s) => s.letter === l)?.colour ?? "#fff");

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 16 }}
      transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
      className="absolute inset-x-4 bottom-4 top-[46%] z-40 flex flex-col overflow-hidden rounded-xl border border-white/10 bg-[#0b0b0f]/95 shadow-2xl backdrop-blur md:inset-x-auto md:left-1/2 md:w-[640px] md:-translate-x-1/2"
    >
      <div className="flex items-center justify-between border-b border-white/[0.07] px-4 py-2.5">
        <span className="text-[11px] uppercase tracking-[0.25em] text-white/50">Live diff feed</span>
        <button onClick={onClose} className="text-[12px] text-white/50 hover:text-white">Close</button>
      </div>
      <div className="flex-1 overflow-y-auto px-2 py-2 font-mono text-[11.5px] leading-[1.55]">
        {diffs.length === 0 && <p className="p-4 text-white/30">Nothing has been written yet.</p>}
        {diffs.map((d) => (
          <div key={d.seq} className="mb-2">
            <div className="flex items-center gap-2 px-2 py-0.5 text-white/45">
              <span className="font-semibold" style={{ color: colourOf(d.seat) }}>{d.seat === MODERATOR ? "MOD" : d.seat}</span>
              <span className="text-white/60">{d.file}</span>
              <span className="text-emerald-400/80">+{d.added}</span>
              <span className="text-red-400/80">−{d.removed}</span>
            </div>
            {d.lines.map((l, i) => (
              <div
                key={i}
                className={`flex gap-2 rounded-sm px-2 ${l.op === "+" ? "bg-emerald-500/[0.07] text-emerald-300/90" : "bg-red-500/[0.08] text-red-300/90"}`}
              >
                <span className="w-5 shrink-0 text-right opacity-60" style={{ color: colourOf(d.seat) }}>{d.seat === MODERATOR ? "·" : d.seat}</span>
                <span className="w-3 shrink-0">{l.op}</span>
                <span className="whitespace-pre-wrap break-words">{l.text || " "}</span>
              </div>
            ))}
            {d.added + d.removed > d.lines.length && (
              <div className="px-9 text-white/25">… {d.added + d.removed - d.lines.length} more lines</div>
            )}
          </div>
        ))}
        <div ref={end} />
      </div>
    </motion.div>
  );
}
