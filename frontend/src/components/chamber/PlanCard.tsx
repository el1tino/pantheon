"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { SeatView } from "@/lib/chamber/reducer";
import { Checkpoint } from "@/lib/chamber/types";

type Props = {
  checkpoint: Extract<Checkpoint, { kind: "plan" }>;
  seats: SeatView[];
  onApprove: (assignments: Record<string, { owner: string; reviewer: string }>) => Promise<void>;
};

/** Checkpoint 2: the council's task plan. Approve it, swapping any owner or reviewer first. */
export default function PlanCard({ checkpoint, seats, onApprove }: Props) {
  const [assign, setAssign] = useState(() =>
    Object.fromEntries(checkpoint.tasks.map((t) => [t.id, { owner: t.owner ?? "", reviewer: t.reviewer ?? "" }])),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seat = (l: string | null) => seats.find((s) => s.letter === l);
  const choices = checkpoint.seats;
  const clash = checkpoint.tasks.filter((t) => assign[t.id].owner === assign[t.id].reviewer).map((t) => t.id);

  const approve = async () => {
    setBusy(true);
    setError(null);
    const changed = Object.fromEntries(
      checkpoint.tasks
        .filter((t) => assign[t.id].owner !== t.owner || assign[t.id].reviewer !== t.reviewer)
        .map((t) => [t.id, assign[t.id]]),
    );
    try {
      await onApprove(changed);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const select = (tid: string, field: "owner" | "reviewer") => (
    <select
      value={assign[tid][field]}
      onChange={(e) => setAssign((a) => ({ ...a, [tid]: { ...a[tid], [field]: e.target.value } }))}
      className="rounded-md border border-white/15 bg-[#121218] px-1.5 py-1 text-[12px] outline-none"
      style={{ color: seat(assign[tid][field])?.colour }}
    >
      {choices.map((c) => (
        <option key={c} value={c} style={{ color: seat(c)?.colour }}>{c} · {seat(c)?.name}</option>
      ))}
    </select>
  );

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/55 p-4 backdrop-blur-[2px]">
      <motion.div
        initial={{ opacity: 0, y: 28, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        className="flex max-h-full w-[min(860px,96vw)] flex-col rounded-2xl border border-amber-200/20 bg-[#0d0c10]/95 shadow-2xl"
      >
        <div className="border-b border-white/[0.06] px-6 pb-4 pt-5">
          <div className="mb-1 text-[10px] uppercase tracking-[0.3em] text-amber-200/70">Checkpoint · approve the plan</div>
          <h2 className="text-lg font-medium text-white">Who builds what</h2>
          <p className="mt-1 text-[12.5px] text-white/45">
            Leads were voted in by the other members. Every task is reviewed by a different model. Swap anyone before approving.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {checkpoint.workstreams.map((w) => (
              <span key={w.id} className="flex items-center gap-1.5 rounded-full border border-white/10 px-2.5 py-1 text-[12px] text-white/75">
                <span className="h-2 w-2 rounded-full" style={{ background: seat(w.lead)?.colour, boxShadow: `0 0 6px ${seat(w.lead)?.colour}` }} />
                {w.title}: <span style={{ color: seat(w.lead)?.colour }}>{seat(w.lead)?.name}</span>
                {w.votes > 0 && <span className="font-mono text-[10.5px] text-white/35">{w.votes} vote{w.votes === 1 ? "" : "s"}</span>}
              </span>
            ))}
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-3">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="text-left text-[10.5px] uppercase tracking-[0.15em] text-white/35">
                <th className="py-2 pr-3 font-normal">Task</th>
                <th className="py-2 pr-3 font-normal">Files</th>
                <th className="py-2 pr-3 font-normal">Builds</th>
                <th className="py-2 font-normal">Reviews</th>
              </tr>
            </thead>
            <tbody>
              {checkpoint.tasks.map((t) => (
                <tr key={t.id} className="border-t border-white/[0.06] align-top">
                  <td className="py-2.5 pr-3">
                    <div className="text-white/90">{t.title} <span className="font-mono text-[10.5px] text-white/30">{t.id}</span></div>
                    {t.brief && <div className="mt-0.5 text-[11.5px] text-white/45">{t.brief}</div>}
                    {t.depends_on.length > 0 && <div className="mt-0.5 text-[10.5px] text-white/30">after {t.depends_on.join(", ")}</div>}
                  </td>
                  <td className="py-2.5 pr-3 font-mono text-[11px] text-white/55">{t.files.join("\n")}</td>
                  <td className="py-2.5 pr-3">{select(t.id, "owner")}</td>
                  <td className="py-2.5">{select(t.id, "reviewer")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex items-center gap-3 border-t border-white/[0.06] px-6 py-4">
          {clash.length > 0 ? (
            <span className="text-[12px] text-red-300">{clash.join(", ")}: the reviewer must be a different seat.</span>
          ) : (
            <span className="text-[12px] text-white/35">{error ?? "Approving starts the build."}</span>
          )}
          <button
            disabled={busy || clash.length > 0}
            onClick={approve}
            className="ml-auto rounded-md bg-amber-300 px-4 py-2 text-[13px] font-medium text-black disabled:opacity-40"
          >
            Approve and build
          </button>
        </div>
      </motion.div>
    </div>
  );
}
