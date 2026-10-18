"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import Markdown from "@/components/Markdown";
import { SeatView } from "@/lib/chamber/reducer";
import { CheckView, Deliverable, ImageView } from "@/lib/chamber/types";
import Gallery from "./Gallery";

type Props = {
  runId: string;
  deliverable: Deliverable;
  images: ImageView[];
  seats: SeatView[];
  siteVersion: number;
  lastCheck: CheckView | null;
  onClose: () => void;
};

const CHECK_LABEL: Record<string, string> = {
  passed: "Checked in Docker: passed",
  failed: "Checked in Docker: still failing",
  not_run: "Not run: unverified",
};

/** The finished deliverable, readable in place, with copy and download. */
export default function ResultPanel({ runId, deliverable, images, seats, siteVersion, lastCheck, onClose }: Props) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(deliverable.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  };
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 20 }}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
      className="absolute inset-x-3 bottom-3 top-14 z-40 flex flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#0b0b0f]/95 shadow-2xl backdrop-blur md:inset-x-auto md:left-1/2 md:w-[720px] md:-translate-x-1/2"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-white/[0.07] px-5 py-3">
        <span className="text-[10px] uppercase tracking-[0.3em] text-amber-200/70">Result</span>
        <span className="min-w-0 truncate text-[13px] text-white/70">{deliverable.title}</span>
        {lastCheck && (
          <span
            className={`whitespace-nowrap rounded-full border px-2 py-0.5 text-[10.5px] ${
              lastCheck.status === "passed" ? "border-emerald-400/40 text-emerald-300"
                : lastCheck.status === "failed" ? "border-red-400/40 text-red-300" : "border-amber-300/40 text-amber-200"
            }`}
          >
            {CHECK_LABEL[lastCheck.status]}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <button onClick={copy} className="rounded-md border border-white/10 px-2.5 py-1 text-[12px] text-white/70 hover:border-white/30">
            {copied ? "Copied" : "Copy"}
          </button>
          <a
            href={`/api/runs/${runId}/files/${deliverable.path}`}
            className="rounded-md border border-white/10 px-2.5 py-1 text-[12px] text-white/70 hover:border-white/30"
          >
            Download
          </a>
          <button onClick={onClose} className="px-2 text-[12px] text-white/45 hover:text-white">Close</button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-5 text-[14px] text-white/80">
        {images.length > 0 && (
          <div className="mb-6">
            <Gallery images={images} seats={seats} version={siteVersion} />
          </div>
        )}
        <Markdown text={deliverable.content} />
      </div>
    </motion.div>
  );
}
