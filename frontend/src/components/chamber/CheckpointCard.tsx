"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import Markdown from "@/components/Markdown";
import { SeatView } from "@/lib/chamber/reducer";
import { Checkpoint } from "@/lib/chamber/types";
import Gallery from "./Gallery";
import SitePreview from "./SitePreview";

type Props = {
  checkpoint: Extract<Checkpoint, { kind: "pick" | "review" }>;
  seats: SeatView[];
  siteVersion: number;
  onAnswer: (answer: { action: string; option?: string; note?: string }) => Promise<void>;
};

/** The council stops and the client decides: pick an option, or review the result. */
export default function CheckpointCard({ checkpoint, seats, siteVersion, onAnswer }: Props) {
  const gallery = checkpoint.kind === "review" && !checkpoint.preview ? checkpoint.images ?? [] : [];
  const check = checkpoint.kind === "review" ? checkpoint.check : null;
  const preview = checkpoint.kind === "review" ? checkpoint.preview : null;
  const [view, setView] = useState<"site" | "text">(preview ? "site" : "text");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [changing, setChanging] = useState(false);
  const [note, setNote] = useState("");
  const colourOf = (l: string) => seats.find((s) => s.letter === l)?.colour ?? "#fff";
  const nameOf = (l: string) => seats.find((s) => s.letter === l)?.name ?? l;

  const answer = async (a: { action: string; option?: string; note?: string }) => {
    setBusy(true);
    setError(null);
    try {
      await onAnswer(a);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <div className="glass-scrim absolute inset-0 z-50 flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, y: 28, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        className={`glass-thick flex max-h-full flex-col rounded-[22px] !border-amber-200/15 ${
          preview || gallery.length ? "h-[min(860px,96%)] w-[min(1100px,96vw)]" : "w-[min(760px,96vw)]"
        }`}
        style={{ boxShadow: "0 0 80px rgba(253, 230, 138, 0.08)" }}
      >
        <div className="border-b border-white/[0.06] px-6 pb-4 pt-5">
          <div className="mb-1 text-[10px] uppercase tracking-[0.3em] text-amber-200/70">Checkpoint · your call</div>
          <h2 className="text-lg font-medium text-white">
            {checkpoint.kind === "pick" ? "The council's top options" : `Review: ${checkpoint.title}`}
          </h2>
          <p className="mt-1 text-[12.5px] text-white/45">
            {checkpoint.kind === "pick"
              ? "Each option was scored 1 to 5 by the other members, without knowing who wrote it."
              : "Accept it, or tell the council what to change and it will revise."}
          </p>
          {check && (
            <p className={`mt-2 text-[12px] ${check.status === "passed" ? "text-emerald-300/90" : check.status === "failed" ? "text-red-300/90" : "text-amber-200/90"}`}>
              {check.status === "passed"
                ? `Checked in Docker (${check.path}): the site loads, its scripts run and every file it uses exists.`
                : check.status === "failed"
                  ? `Still failing in Docker (${check.path}): ${check.errors.length} error(s) after the fix loops.`
                  : "The site was not run (Docker unavailable), so it is unverified."}
            </p>
          )}
          {preview && (
            <div className="mt-3 flex gap-1">
              {(["site", "text"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  className={`rounded-md px-2.5 py-1 text-[12px] ${view === v ? "bg-white/[0.08] text-white" : "text-white/45 hover:text-white"}`}
                >
                  {v === "site" ? "Site preview" : checkpoint.kind === "review" ? checkpoint.title : ""}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {checkpoint.kind === "pick" ? (
            <div className="grid gap-3">
              {checkpoint.options.map((o, i) => (
                <motion.button
                  key={o.id}
                  disabled={busy}
                  onClick={() => answer({ action: "pick", option: o.id })}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.15 + i * 0.08 }}
                  className="group relative rounded-xl border border-white/10 bg-white/[0.025] p-4 text-left transition-colors hover:bg-white/[0.05] disabled:opacity-50"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="text-[15px] font-medium text-white">{o.title}</div>
                      <div className="mt-1 text-[13px] leading-relaxed text-white/60">{o.summary}</div>
                      <div className="mt-2 flex items-center gap-1.5 text-[11px] text-white/40">
                        <span className="h-1.5 w-1.5 rounded-full" style={{ background: colourOf(o.seat), boxShadow: `0 0 6px ${colourOf(o.seat)}` }} />
                        proposed by {nameOf(o.seat)} · {o.id}
                      </div>
                    </div>
                    <div className="shrink-0 text-right">
                      <div className="font-mono text-2xl tabular-nums text-amber-200">{o.score.toFixed(1)}</div>
                      <div className="text-[10.5px] text-white/35">{o.votes} score{o.votes === 1 ? "" : "s"}</div>
                    </div>
                  </div>
                  <span className="absolute bottom-3 right-4 text-[11px] text-white/0 transition-colors group-hover:text-white/60">Pick this →</span>
                </motion.button>
              ))}
            </div>
          ) : gallery.length > 0 ? (
            <div className="space-y-5">
              <Gallery images={gallery} seats={seats} version={siteVersion} />
              <div className="glass-well rounded-xl p-4 text-[13.5px] text-white/80">
                <Markdown text={checkpoint.kind === "review" ? checkpoint.content : ""} />
              </div>
            </div>
          ) : preview && view === "site" ? (
            <SitePreview version={siteVersion} className="min-h-[50vh]" />
          ) : (
            <div className="glass-well rounded-xl p-4 text-[13.5px] text-white/80">
              <Markdown text={checkpoint.content} />
            </div>
          )}
        </div>

        <div className="border-t border-white/[0.06] px-6 py-4">
          {error && <p className="mb-2 text-[12px] text-red-300">{error}</p>}
          {checkpoint.kind === "pick" ? (
            <div className="flex items-center justify-between gap-3">
              <span className="text-[12px] text-white/35">Click an option to choose it.</span>
              {checkpoint.can_retry && (
                <button
                  disabled={busy}
                  onClick={() => answer({ action: "another_round" })}
                  className="glass-button rounded-full px-3 py-2 text-[13px] text-white/75 disabled:opacity-40"
                >
                  None of these: another round
                </button>
              )}
            </div>
          ) : changing ? (
            <div className="flex flex-col gap-2">
              <textarea
                autoFocus
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={3}
                placeholder="What should change?"
                className="glass-well w-full resize-none rounded-xl p-3 text-[13px] text-white outline-none"
              />
              <div className="flex justify-end gap-2">
                <button onClick={() => setChanging(false)} className="px-3 py-2 text-[13px] text-white/50 hover:text-white">Back</button>
                <button
                  disabled={busy || !note.trim()}
                  onClick={() => answer({ action: "changes", note: note.trim() })}
                  className="accent-button rounded-full px-4 py-2 text-[13px] font-medium disabled:opacity-40"
                >
                  Send to the council
                </button>
              </div>
            </div>
          ) : (
            <div className="flex justify-end gap-2">
              <button
                disabled={busy}
                onClick={() => setChanging(true)}
                className="glass-button rounded-full px-4 py-2 text-[13px] text-white/80 disabled:opacity-40"
              >
                Request changes
              </button>
              <button
                disabled={busy}
                onClick={() => answer({ action: "accept" })}
                className="accent-button rounded-full px-4 py-2 text-[13px] font-medium disabled:opacity-40"
              >
                Accept
              </button>
            </div>
          )}
        </div>
      </motion.div>
    </div>
  );
}
