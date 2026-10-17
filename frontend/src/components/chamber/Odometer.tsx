"use client";

import { motion } from "framer-motion";

const DIGITS = Array.from({ length: 10 }, (_, i) => i);

function Digit({ value, reduced }: { value: number; reduced: boolean }) {
  return (
    <span className="relative inline-block overflow-hidden" style={{ height: "1em", width: "0.62em" }}>
      <motion.span
        className="absolute left-0 top-0 flex flex-col"
        animate={{ y: `${-value}em` }}
        transition={reduced ? { duration: 0 } : { duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
      >
        {DIGITS.map((d) => (
          <span key={d} style={{ height: "1em", lineHeight: "1em" }}>
            {d}
          </span>
        ))}
      </motion.span>
    </span>
  );
}

/** Counter whose digits roll like an odometer. */
export default function Odometer({ value, minDigits = 3, reduced = false }: { value: number; minDigits?: number; reduced?: boolean }) {
  const digits = String(Math.max(0, Math.floor(value))).padStart(minDigits, "0").split("");
  return (
    <span className="inline-flex font-mono tabular-nums" style={{ lineHeight: "1em" }}>
      {digits.map((d, i) => (
        <Digit key={digits.length - i} value={Number(d)} reduced={reduced} />
      ))}
    </span>
  );
}
