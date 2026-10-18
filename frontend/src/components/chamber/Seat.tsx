"use client";

import { AnimatePresence, motion } from "framer-motion";
import { SeatSpot } from "@/lib/chamber/geometry";
import { SeatView } from "@/lib/chamber/reducer";

type Props = { seat: SeatView; spot: SeatSpot; compact: boolean; reducedMotion: boolean };

const GREY = "#5b5f66";

export default function Seat({ seat, spot, compact, reducedMotion }: Props) {
  const absent = seat.status === "absent";
  const speaking = seat.status === "speaking";
  const thinking = seat.status === "thinking";
  const colour = absent ? GREY : seat.colour;
  const size = spot.size;

  const letterAnim = absent
    ? { opacity: 0.35, scale: 1 }
    : speaking
      ? { opacity: 1, scale: 1.1 }
      : thinking
        ? reducedMotion ? { opacity: 0.9, scale: 1 } : { opacity: [0.7, 1, 0.7], scale: [1, 1.025, 1] }
        : reducedMotion ? { opacity: 0.62, scale: 1 } : { opacity: [0.5, 0.72, 0.5], scale: 1 };
  const letterTransition =
    thinking && !reducedMotion
      ? { duration: 1.3, repeat: Infinity, ease: "easeInOut" as const }
      : !speaking && !absent && !reducedMotion
        ? { duration: 4.2, repeat: Infinity, ease: "easeInOut" as const }
        : { duration: 0.45, ease: [0.22, 1, 0.36, 1] as const };

  return (
    <div
      className="absolute z-10 flex -translate-x-1/2 flex-col items-center"
      style={{ left: spot.x, top: spot.y - size * 0.62 }}
    >
      {/* caption bubble: streams the first line of what the seat is saying */}
      <AnimatePresence>
        {speaking && seat.caption && (
          <motion.div
            key="caption"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.3 }}
            className={`absolute bottom-full z-30 mb-3 w-max max-w-[min(280px,60vw)] rounded-lg border bg-black/75 px-3 py-1.5 text-left text-[12px] leading-snug text-white/90 shadow-lg backdrop-blur ${spot.align === "start" ? "left-[-12px]" : spot.align === "end" ? "right-[-12px]" : ""}`}
            style={{ borderColor: `${colour}55`, boxShadow: `0 0 24px ${colour}22` }}
          >
            <span className="line-clamp-2">{seat.caption}</span>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="relative flex items-center justify-center" style={{ height: size * 1.12 }}>
        {/* expanding ring when a seat starts speaking */}
        <AnimatePresence>
          {speaking && !reducedMotion && (
            <motion.span
              key="ring"
              className="pointer-events-none absolute rounded-full border"
              style={{ width: size * 1.1, height: size * 1.1, borderColor: colour }}
              initial={{ scale: 0.6, opacity: 0.7 }}
              animate={{ scale: 2.1, opacity: 0 }}
              transition={{ duration: 1.3, ease: "easeOut" }}
            />
          )}
        </AnimatePresence>
        <motion.span
          className="select-none font-semibold leading-none"
          style={{
            fontSize: size,
            color: colour,
            textShadow: absent ? "none" : `0 0 ${speaking ? 36 : 18}px ${colour}${speaking ? "aa" : "55"}`,
            letterSpacing: "-0.02em",
          }}
          animate={letterAnim}
          transition={letterTransition}
        >
          {seat.letter}
        </motion.span>
      </div>

      {/* pedestal */}
      <div className="relative mt-1 overflow-hidden" style={{ width: size * 1.35, height: 3 }}>
        {absent ? (
          <div className="h-0 w-full border-t-2 border-dashed" style={{ borderColor: GREY }} />
        ) : (
          <div
            className="h-full w-full rounded-full"
            style={{
              background: colour,
              opacity: speaking ? 1 : 0.7,
              boxShadow: `0 0 ${speaking ? 18 : 10}px ${colour}`,
            }}
          />
        )}
        {thinking && !reducedMotion && <div className="pedestal-shimmer absolute inset-0" />}
      </div>

      <div className="mt-2 flex flex-col items-center gap-1 whitespace-nowrap">
        <span className={`text-[12px] ${absent ? "text-white/30" : "text-white/75"}`}>
          {seat.name}
          {absent && " · absent"}
        </span>
        {!compact && seat.role && (
          <span
            className="rounded-full border px-2 py-[1px] text-[9.5px] uppercase tracking-[0.12em]"
            style={{ borderColor: `${colour}44`, color: `${colour}cc` }}
            title={seat.role}
          >
            {seat.role}
          </span>
        )}
        <span className="font-mono text-[10.5px] tabular-nums">
          <span className="text-emerald-400/80">+{seat.plus}</span>{" "}
          <span className="text-red-400/80">−{seat.minus}</span>
        </span>
      </div>
    </div>
  );
}
