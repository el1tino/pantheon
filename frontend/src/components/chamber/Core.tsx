"use client";

import { AnimatePresence, motion } from "framer-motion";
import Odometer from "./Odometer";

type Props = {
  x: number;
  y: number;
  width: number;
  plus: number;
  minus: number;
  flash: { key: number; kind: "add" | "remove" } | null;
  decision: { title: string; colour: string; by: string } | null;
  onOpen: () => void;
  reducedMotion: boolean;
};

/** The thing everyone is building: a glowing bar with live +/− counters. */
export default function Core({ x, y, width, plus, minus, flash, decision, onOpen, reducedMotion }: Props) {
  const strength = Math.min(1, Math.log10(1 + plus) / 2.6); // glow grows with the project
  const glow = 10 + strength * 46;
  return (
    <div className="absolute z-10 -translate-x-1/2" style={{ left: x, top: y - 7, width }}>
      <button
        type="button"
        onClick={onOpen}
        className="group relative block h-[14px] w-full cursor-pointer rounded-full focus:outline-none focus-visible:ring-1 focus-visible:ring-white/40"
        aria-label="Open the live diff feed"
        title="Open the live diff feed"
      >
        <span
          className="absolute inset-0 rounded-full"
          style={{
            background:
              "linear-gradient(90deg, rgba(255,255,255,0.05), rgba(255,236,210,0.55) 50%, rgba(255,255,255,0.05))",
            boxShadow: `0 0 ${glow}px rgba(255, 214, 160, ${0.18 + strength * 0.35}), inset 0 0 6px rgba(255,255,255,0.4)`,
          }}
        />
        <span className="absolute inset-x-[18%] top-1/2 h-px -translate-y-1/2 bg-white/80 blur-[0.5px]" />
        <AnimatePresence>
          {flash && (
            <motion.span
              key={flash.key}
              className="absolute -inset-1 rounded-full"
              style={{
                background: flash.kind === "add" ? "#4ade80" : "#f87171",
                boxShadow: `0 0 40px ${flash.kind === "add" ? "#4ade80" : "#f87171"}`,
              }}
              initial={{ opacity: reducedMotion ? 0.35 : 0.7 }}
              animate={{ opacity: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.9, ease: "easeOut" }}
            />
          )}
        </AnimatePresence>
        <span className="absolute -top-6 left-1/2 -translate-x-1/2 whitespace-nowrap text-[10px] uppercase tracking-[0.3em] text-white/30 transition-colors group-hover:text-white/60">
          Project core
        </span>
      </button>

      <div className="mt-4 flex items-center justify-center gap-8 text-[22px]">
        <span className="flex items-center gap-1.5 text-emerald-400" style={{ textShadow: "0 0 18px rgba(74,222,128,0.35)" }}>
          <span className="text-[18px]">+</span>
          <Odometer value={plus} reduced={reducedMotion} />
        </span>
        <span className="flex items-center gap-1.5 text-red-400" style={{ textShadow: "0 0 18px rgba(248,113,113,0.3)" }}>
          <span className="text-[18px]">−</span>
          <Odometer value={minus} reduced={reducedMotion} />
        </span>
      </div>

      <AnimatePresence>
        {decision && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.4 }}
            className="mx-auto mt-5 w-max max-w-[min(560px,80vw)] glass-chip rounded-full px-4 py-1.5 text-center text-[13px] text-white/85"
            style={{ borderColor: `${decision.colour}66`, boxShadow: `0 0 30px ${decision.colour}22` }}
          >
            <span className="mr-2 text-[10px] uppercase tracking-[0.2em]" style={{ color: decision.colour }}>
              Decided by {decision.by}
            </span>
            {decision.title}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
