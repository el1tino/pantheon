"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import Markdown from "@/components/Markdown";
import { SeatView } from "@/lib/chamber/reducer";
import { CLIENT, MODERATOR, Message, STANCE_COLOUR, STANCE_LABEL } from "@/lib/chamber/types";

type Props = {
  seats: SeatView[];
  messages: Message[];
  live: Record<string, string>;
  thinking: string | null;
  tally: Record<string, number>;
  scores: Record<string, number[]>;
};

type OptionItem = { title?: string; summary?: string };

const avg = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;

/** Long pieces of work collapse so the conversation stays readable. */
function Collapsible({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 420;
  return (
    <div>
      <div className={!open && long ? "relative max-h-40 overflow-hidden" : ""}>
        <Markdown text={text} className="text-[13px] text-white/80" />
        {!open && long && <div className="absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-[#0e0e12] to-transparent" />}
      </div>
      {long && (
        <button onClick={() => setOpen(!open)} className="mt-1 text-[11.5px] text-white/45 hover:text-white">
          {open ? "Show less" : "Show all"}
        </button>
      )}
    </div>
  );
}

export default function Transcript({ seats, messages, live, thinking, tally, scores }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const seatOf = (letter: string) => seats.find((s) => s.letter === letter);
  const byId = new Map(messages.map((m) => [m.id, m]));

  const liveLength = Object.values(live).reduce((n, text) => n + text.length, 0);
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 200;
    if (nearBottom) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages.length, liveLength]);

  const header = (letter: string, extra?: React.ReactNode) => {
    if (letter === MODERATOR) return <span className="text-[12px] font-medium text-white/85">Moderator</span>;
    if (letter === CLIENT) return <span className="text-[12px] font-medium text-white">You · client</span>;
    const s = seatOf(letter);
    return (
      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-[12.5px] font-medium" style={{ color: s?.colour }}>
          {letter} · {s?.name}
        </span>
        {s?.role && (
          <span className="rounded-full border border-white/10 px-1.5 text-[9.5px] uppercase tracking-[0.1em] text-white/45">
            {s.role}
          </span>
        )}
        {extra}
      </span>
    );
  };

  const optionScore = (id: string) =>
    scores[id]?.length ? (
      <span className="ml-2 font-mono text-[10.5px] text-amber-200/80">
        {avg(scores[id]).toFixed(1)}★ · {scores[id].length}
      </span>
    ) : null;

  // Option ids are numbered across the run in the order they were proposed.
  const optionIds = new Map<string, string[]>();
  let optionSeq = 0;
  for (const m of messages) {
    const opts = m.proposal?.options as OptionItem[] | undefined;
    if (Array.isArray(opts)) optionIds.set(m.id, opts.map(() => `o${++optionSeq}`));
  }

  return (
    <div ref={scroller} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
      {messages.length === 0 && Object.keys(live).length === 0 && (
        <p className="pt-10 text-center text-[13px] text-white/30">The council is taking its seats…</p>
      )}
      {messages.map((m) => {
        if (m.seat === CLIENT) {
          return (
            <motion.div key={m.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
              className="ml-6 rounded-lg border border-white/20 bg-white/[0.07] px-3 py-2 text-[13px] text-white">
              <div className="mb-0.5 text-[10px] uppercase tracking-[0.2em] text-white/50">You · direct instruction</div>
              {m.content}
            </motion.div>
          );
        }
        if (m.seat === MODERATOR) {
          const big = m.round === "summary" || m.round === "verdict";
          return big ? (
            <motion.div key={m.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
              className="rounded-lg border border-white/15 bg-white/[0.04] p-3 text-[12.5px] leading-relaxed text-white/75">
              <div className="mb-2 text-[10px] uppercase tracking-[0.25em] text-white/45">
                {m.round === "verdict" ? "The result" : "Moderator summary"}
              </div>
              <Collapsible text={m.content} />
            </motion.div>
          ) : (
            <motion.div key={m.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }}
              className="flex gap-2 px-1 text-[12px] italic leading-relaxed text-white/45">
              <span className="not-italic text-white/30">◇</span>
              <span>{m.content}</span>
            </motion.div>
          );
        }
        const colour = seatOf(m.seat)?.colour ?? "#fff";
        const target = m.reply_to ? byId.get(m.reply_to) : null;
        const opts = m.proposal?.options as OptionItem[] | undefined;
        const nominated = m.proposal?.parts as string[] | undefined;
        const wrote = m.proposal?.files as string[] | undefined;
        const work = m.stance === "report";
        return (
          <motion.div
            key={m.id}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
            className="relative rounded-md bg-white/[0.025] py-2 pl-3.5 pr-3"
          >
            <span className="absolute inset-y-1.5 left-0 w-[3px] rounded-full" style={{ background: colour, boxShadow: `0 0 8px ${colour}88` }} />
            <div className="mb-1 flex items-start justify-between gap-2">
              {header(
                m.seat,
                <>
                <span
                  className="rounded px-1.5 text-[10px] font-medium uppercase tracking-[0.08em]"
                  style={{ color: STANCE_COLOUR[m.stance], background: `${STANCE_COLOUR[m.stance]}14` }}
                >
                  {work ? (m.round === "revise" ? "Revises" : "Writes") : STANCE_LABEL[m.stance] ?? m.stance}
                  {target && (
                    <span className="normal-case tracking-normal text-white/40">
                      {" "}→ {target.seat === MODERATOR ? "moderator" : target.seat === CLIENT ? "you" : seatOf(target.seat)?.name} ({m.reply_to})
                    </span>
                  )}
                </span>
                {m.unverified && (
                  <span
                    className="rounded border border-amber-300/40 px-1.5 text-[10px] font-medium uppercase tracking-[0.08em] text-amber-200"
                    title="This claims success but points at no artifact or passing check log, so it is not verified."
                  >
                    Unverified
                  </span>
                )}
                </>,
              )}
              <span className="shrink-0 font-mono text-[10px] text-white/25">{m.id}</span>
            </div>
            {work ? <Collapsible text={m.content} /> : <p className="text-[13px] leading-relaxed text-white/80">{m.content}</p>}
            {Array.isArray(opts) && (
              <div className="mt-2 space-y-1.5">
                {opts.map((o, i) => {
                  const id = optionIds.get(m.id)?.[i] ?? "";
                  return (
                    <div key={i} className="rounded border px-2.5 py-1.5 text-[12px]" style={{ borderColor: `${colour}33`, background: `${colour}0d` }}>
                      <span className="font-medium" style={{ color: colour }}>◆ {o.title}</span>
                      {o.summary && <span className="text-white/60"> — {o.summary}</span>}
                      <span className="ml-1 font-mono text-[10px] text-white/30">{id}</span>
                      {optionScore(id)}
                    </div>
                  );
                })}
              </div>
            )}
            {Array.isArray(nominated) && (
              <div className="mt-1.5 text-[11.5px] text-white/45">
                {nominated.length ? `Puts itself forward for ${nominated.join(", ")}` : "Would rather review"}
              </div>
            )}
            {Array.isArray(m.proposal?.images) && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {(m.proposal.images as { path: string; kind: string }[]).map((img) => (
                  <span key={img.path} className="rounded bg-amber-200/10 px-1.5 py-0.5 font-mono text-[10.5px] text-amber-100/80">
                    asks for {img.kind}: {img.path}
                  </span>
                ))}
              </div>
            )}
            {typeof m.proposal?.prompt === "string" && (
              <div className="mt-1.5 rounded border border-white/10 px-2 py-1 text-[11.5px] italic text-white/55">
                “{m.proposal.prompt as string}”
                {m.proposal.consultant ? <span className="not-italic text-white/35"> · {String(m.proposal.consultant)}</span> : null}
              </div>
            )}
            {Array.isArray(wrote) && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {wrote.map((f) => (
                  <span key={f} className="rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10.5px] text-white/60">{f}</span>
                ))}
              </div>
            )}
            {m.proposal && !opts && !nominated && !wrote && !m.proposal.question && !m.proposal.prompt && (
              <div className="mt-2 rounded border px-2.5 py-1.5 text-[12px]" style={{ borderColor: `${colour}33`, background: `${colour}0d` }}>
                <span className="font-medium" style={{ color: colour }}>◆ {String(m.proposal.title ?? "Proposal")}</span>
                {m.proposal.summary ? <span className="text-white/60"> — {String(m.proposal.summary)}</span> : null}
                {tally[m.id] !== undefined && (
                  <span className="ml-2 font-mono text-[10.5px] text-white/50">{tally[m.id]} vote{tally[m.id] === 1 ? "" : "s"}</span>
                )}
              </div>
            )}
            {m.votes && m.votes.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {m.votes.map((v, i) => {
                  const part = (v as { part?: string }).part;
                  const label = part ? `${part} → ${v.target}` : m.round === "score" ? `${v.target} ${v.score}★` : v.target;
                  return (
                    <span key={i} className="rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10.5px] text-white/60">{label}</span>
                  );
                })}
              </div>
            )}
          </motion.div>
        );
      })}
      {Object.entries(live).map(([seat, text]) => (
        <div key={`live-${seat}`} className="relative rounded-md bg-white/[0.04] py-2 pl-3.5 pr-3">
          <span
            className="absolute inset-y-1.5 left-0 w-[3px] animate-pulse rounded-full"
            style={{ background: seat === MODERATOR ? "#fff" : seatOf(seat)?.colour }}
          />
          <div className="mb-1">{header(seat)}</div>
          <p className="max-h-48 overflow-hidden whitespace-pre-wrap text-[13px] leading-relaxed text-white/70">
            {text.length > 600 ? "…" + text.slice(-600) : text || (
              <span className="text-white/35">{thinking === seat || !text ? "thinking…" : ""}</span>
            )}
            <span className="ml-0.5 inline-block h-3.5 w-[2px] translate-y-0.5 animate-pulse bg-white/60" />
          </p>
        </div>
      ))}
    </div>
  );
}
