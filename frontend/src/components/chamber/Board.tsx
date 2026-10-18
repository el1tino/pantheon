"use client";

import { motion } from "framer-motion";
import { SeatView } from "@/lib/chamber/reducer";
import { TaskView } from "@/lib/chamber/types";
import SeatLogo from "@/components/SeatLogo";

type Props = { tasks: Record<string, TaskView>; seats: SeatView[]; onClose: () => void };

const COLUMNS: { key: string; label: string; statuses: string[] }[] = [
  { key: "planned", label: "Planned", statuses: ["planned", "assigned"] },
  { key: "building", label: "Building", statuses: ["building", "doing", "reassigned", "revising"] },
  { key: "blocked", label: "Blocked", statuses: ["blocked"] },
  { key: "review", label: "In review", statuses: ["in_review"] },
  { key: "changes", label: "Changes", statuses: ["changes"] },
  { key: "done", label: "Done", statuses: ["done"] },
];

/** The team board: every task with its owner, reviewer, files and any question thread. */
export default function Board({ tasks, seats, onClose }: Props) {
  const seat = (l: string | null) => seats.find((s) => s.letter === l);
  const all = Object.values(tasks);
  const leads = all.filter((t) => t.kind === "workstream");
  const build = all.filter((t) => t.kind === "task");
  const cards = build.length ? build : all.filter((t) => t.kind === "part");

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 20 }}
      transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      className="absolute inset-3 z-40 flex flex-col overflow-hidden glass-thick rounded-[22px]"
    >
      <div className="flex items-center gap-4 border-b border-white/[0.07] px-5 py-3">
        <span className="text-[10px] uppercase tracking-[0.3em] text-white/50">The Board</span>
        <div className="flex flex-wrap gap-2">
          {leads.map((w) => (
            <span key={w.id} className="flex items-center gap-1.5 rounded-full border border-white/10 px-2.5 py-0.5 text-[11.5px] text-white/70">
              {seat(w.owner) ? <SeatLogo seat={seat(w.owner)!} size={12} /> : <span className="h-1.5 w-1.5 rounded-full bg-white/40" />}
              {w.title} · <span style={{ color: seat(w.owner)?.colour }}>{seat(w.owner)?.name ?? w.owner}</span>
            </span>
          ))}
        </div>
        <button onClick={onClose} className="ml-auto text-[12px] text-white/45 hover:text-white">Close</button>
      </div>
      {cards.length === 0 ? (
        <p className="m-auto text-[13px] text-white/35">No tasks yet. They appear once the council has split the work.</p>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-2 gap-3 overflow-auto p-4 md:grid-cols-3 xl:grid-cols-6">
          {COLUMNS.map((col) => {
            const inCol = cards.filter((t) => col.statuses.includes(t.status));
            return (
              <div key={col.key} className="flex min-h-40 flex-col rounded-xl bg-white/[0.02] p-2">
                <div className="mb-2 flex items-center justify-between px-1 text-[11px] uppercase tracking-[0.15em] text-white/45">
                  {col.label}
                  <span className="font-mono text-white/30">{inCol.length}</span>
                </div>
                <div className="space-y-2">
                  {inCol.map((t) => {
                    const owner = seat(t.owner);
                    const reviewer = seat(t.reviewer);
                    return (
                      <motion.div
                        layout
                        key={t.id}
                        className="glass rounded-xl p-2.5"
                        style={{ borderLeft: `3px solid ${owner?.colour ?? "#555"}` }}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <span className="text-[12.5px] font-medium leading-snug text-white/90">{t.title}</span>
                          <span className="font-mono text-[10px] text-white/30">{t.id}</span>
                        </div>
                        {t.workstream && <div className="mt-0.5 text-[10.5px] text-white/35">{t.workstream}</div>}
                        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
                          <span className="inline-flex items-center gap-1" style={{ color: owner?.colour }}>{owner && <SeatLogo seat={owner} size={12} />}{owner?.name ?? t.owner ?? "unassigned"}</span>
                          {reviewer && <span className="text-white/35">review: <span style={{ color: reviewer.colour }}>{reviewer.name}</span></span>}
                        </div>
                        {t.files.length > 0 && (
                          <div className="mt-1.5 flex flex-wrap gap-1">
                            {t.files.map((f) => (
                              <span key={f} className="rounded bg-white/[0.06] px-1.5 font-mono text-[10px] text-white/55">{f}</span>
                            ))}
                          </div>
                        )}
                        {t.dependsOn.length > 0 && (
                          <div className="mt-1 text-[10.5px] text-white/30">after {t.dependsOn.join(", ")}</div>
                        )}
                        {t.question && (
                          <div className="mt-2 rounded border border-dashed border-white/15 p-1.5 text-[11px] leading-snug">
                            <div className="text-white/60">
                              <span style={{ color: owner?.colour }}>{t.owner}</span> → <span style={{ color: seat(t.question.to)?.colour }}>{t.question.to}</span>: {t.question.text}
                            </div>
                            {t.question.answer && <div className="mt-1 text-white/45">↳ {t.question.answer}</div>}
                          </div>
                        )}
                      </motion.div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </motion.div>
  );
}
