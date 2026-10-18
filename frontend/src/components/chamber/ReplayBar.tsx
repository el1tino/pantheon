"use client";

import { useEffect, useRef } from "react";
import { Replay, SPEEDS } from "@/lib/chamber/useReplay";

const fmt = (s: number) => {
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
};

/** Play, pause, speed and a scrubber marked with the run's phases and checkpoints. */
export default function ReplayBar({ replay, clean, onClean }: { replay: Replay; clean: boolean; onClean: () => void }) {
  const { playing, toggle, speed, setSpeed, clock, duration, seek, markers, loaded } = replay;
  const track = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const seekTo = (clientX: number) => {
    const el = track.current;
    if (!el || !duration) return;
    const r = el.getBoundingClientRect();
    const f = Math.min(Math.max((clientX - r.left) / r.width, 0), 1);
    seek(f > 0.99 ? duration : f * duration); // the very end is a few pixels wide

  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input, textarea, select, button")) return;
      if (e.key === " ") {
        e.preventDefault();
        toggle();
      } else if (e.key === "ArrowRight") seek(clock + 5);
      else if (e.key === "ArrowLeft") seek(clock - 5);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle, seek, clock]);

  const pct = duration ? (clock / duration) * 100 : 0;

  return (
    <footer
      className={`glass relative z-30 mx-2 mb-2 flex h-16 shrink-0 items-center gap-3 rounded-2xl px-3 transition-opacity duration-500 md:mx-3 md:mb-3 md:px-4 ${
        clean ? "opacity-0 hover:opacity-100 focus-within:opacity-100" : ""
      }`}
    >
      <button
        onClick={toggle}
        disabled={!loaded}
        aria-label={playing ? "Pause" : "Play"}
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-white/15 text-white/85 disabled:opacity-30"
      >
        {playing ? (
          <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor"><rect x="1" y="1" width="3.5" height="10" rx="1" /><rect x="7.5" y="1" width="3.5" height="10" rx="1" /></svg>
        ) : (
          <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor"><path d="M2.5 1.2v9.6c0 .5.5.8.9.5l7.4-4.8c.4-.3.4-.8 0-1L3.4.7c-.4-.3-.9 0-.9.5z" /></svg>
        )}
      </button>

      <span className="w-[84px] shrink-0 text-[11px] text-white/45">
        {fmt(clock)} / {fmt(duration)}
      </span>

      <div
        ref={track}
        role="slider"
        tabIndex={0}
        aria-label="Replay position"
        aria-valuemin={0}
        aria-valuemax={Math.round(duration)}
        aria-valuenow={Math.round(clock)}
        onPointerDown={(e) => {
          dragging.current = true;
          (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
          seekTo(e.clientX);
        }}
        onPointerMove={(e) => dragging.current && seekTo(e.clientX)}
        onPointerUp={() => (dragging.current = false)}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") seek(clock + 5);
          if (e.key === "ArrowLeft") seek(clock - 5);
        }}
        className="group relative h-10 min-w-0 flex-1 cursor-pointer touch-none outline-none"
      >
        <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-white/10" />
        <div className="absolute left-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-amber-200/70" style={{ width: `${pct}%` }} />
        {markers.map((m, i) => (
          <span
            key={i}
            title={m.kind === "phase" ? `Phase: ${m.label}` : `Checkpoint: ${m.label}`}
            className={`absolute top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full ${
              m.kind === "phase" ? "h-3 w-[2px] bg-white/45" : "h-2 w-2 bg-amber-300 shadow-[0_0_8px_rgba(252,211,77,0.6)]"
            }`}
            style={{ left: `${duration ? (m.at / duration) * 100 : 0}%` }}
          />
        ))}
        <span
          className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white shadow-[0_0_10px_rgba(255,255,255,0.6)] transition-transform group-hover:scale-110"
          style={{ left: `${pct}%` }}
        />
      </div>

      <div className="flex shrink-0 overflow-hidden rounded-lg border border-white/10">
        {SPEEDS.map((s) => (
          <button
            key={s}
            onClick={() => setSpeed(s)}
            aria-pressed={speed === s}
            className={`h-8 px-2 text-[11px] transition-colors sm:px-2.5 ${speed === s ? "bg-white/[0.12] text-white" : "text-white/45 hover:text-white/80"}`}
          >
            {s}×
          </button>
        ))}
      </div>

      <button
        onClick={onClean}
        aria-pressed={clean}
        title="Hide the transcript and controls, for filming"
        className={`hidden h-8 rounded-lg border px-3 text-[12px] sm:block ${clean ? "border-amber-200/50 text-amber-100" : "border-white/10 text-white/55 hover:text-white"}`}
      >
        Clean
      </button>
    </footer>
  );
}
