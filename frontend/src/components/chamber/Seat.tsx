"use client";

import { AnimatePresence, motion } from "framer-motion";
import { SeatSpot } from "@/lib/chamber/geometry";
import { SeatView } from "@/lib/chamber/reducer";
import SeatLogo from "@/components/SeatLogo";

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
      ? { opacity: 1, scale: 1.08 }
      : thinking
        ? reducedMotion ? { opacity: 0.95, scale: 1 } : { opacity: [0.8, 1, 0.8], scale: [1, 1.03, 1] }
        : reducedMotion ? { opacity: 0.8, scale: 1 } : { opacity: [0.72, 0.88, 0.72], scale: 1 };
  const letterTransition =
    thinking && !reducedMotion
      ? { duration: 1.3, repeat: Infinity, ease: "easeInOut" as const }
      : !speaking && !absent && !reducedMotion
        ? { duration: 4.2, repeat: Infinity, ease: "easeInOut" as const }
        : { duration: 0.45, ease: [0.22, 1, 0.36, 1] as const };

  return (
    <div
      className="absolute flex -translate-x-1/2 flex-col items-center"
      // a speaker's caption bubble sits above its neighbours' discs
      style={{ left: spot.x, top: spot.y - size * 0.62, zIndex: speaking ? 20 : 10 }}
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
            className={`glass-chip absolute bottom-full z-30 mb-3 w-max max-w-[min(280px,60vw)] rounded-xl px-3 py-1.5 text-left text-[12px] leading-snug text-white/90 ${spot.align === "start" ? "left-[-12px]" : spot.align === "end" ? "right-[-12px]" : ""}`}
            style={{ borderColor: `${colour}44` }}
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
              style={{ width: size * 1.1, height: size * 1.1, left: "50%", top: "50%", marginLeft: -size * 0.55, marginTop: -size * 0.55, borderColor: colour }}
              initial={{ scale: 0.6, opacity: 0.7 }}
              animate={{ scale: 2.1, opacity: 0 }}
              transition={{ duration: 1.3, ease: "easeOut" }}
            />
          )}
        </AnimatePresence>
        {/* the seat: its provider's logo on a glass disc that glows in the seat's colour */}
        <motion.div
          className="seat-disc relative flex items-center justify-center rounded-full"
          style={{
            width: size * 1.08,
            height: size * 1.08,
            borderColor: absent ? "rgba(255,255,255,0.08)" : `${colour}${speaking ? "aa" : "44"}`,
            boxShadow: absent
              ? "none"
              : `0 0 ${speaking ? 40 : 22}px -4px ${colour}${speaking ? "99" : "44"}, inset 0 1px 0 rgba(255,255,255,0.14)`,
          }}
          animate={letterAnim}
          transition={letterTransition}
        >
          <SeatLogo seat={seat} size={size * 0.5} dim={absent} />
          <span
            className="glass-chip absolute -bottom-1 -right-1 flex items-center justify-center rounded-full font-mono font-medium leading-none"
            style={{ width: Math.max(16, size * 0.3), height: Math.max(16, size * 0.3), fontSize: Math.max(9, size * 0.15), color: absent ? GREY : colour }}
            aria-hidden
          >
            {seat.letter}
          </span>
        </motion.div>
      </div>

      {/* pedestal */}
      <div className="relative mt-2 overflow-hidden rounded-full" style={{ width: size * 0.9, height: 2 }}>
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
