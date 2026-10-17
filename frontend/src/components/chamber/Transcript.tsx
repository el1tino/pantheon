"use client";

import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { SeatView } from "@/lib/chamber/reducer";
import { MODERATOR, Message, STANCE_COLOUR, STANCE_LABEL } from "@/lib/chamber/types";

type Props = {
  seats: SeatView[];
  messages: Message[];
  live: { seat: string; text: string } | null;
  thinking: string | null;
  tally: Record<string, number>;
};

function Markdownish({ text }: { text: string }) {
  // Just enough for the moderator's summary: **bold** headings and "- " bullets.
  return (
    <div className="space-y-1.5">
      {text.split("\n").filter((l) => l.trim()).map((line, i) => {
        const bullet = line.trim().startsWith("- ");
        const body = (bullet ? line.trim().slice(2) : line).split(/(\*\*[^*]+\*\*)/g).map((part, j) =>
          part.startsWith("**") && part.endsWith("**") ? (
            <strong key={j} className="font-semibold text-white">{part.slice(2, -2)}</strong>
          ) : (
            <span key={j}>{part}</span>
          ),
        );
        return bullet ? (
          <div key={i} className="flex gap-2 pl-1"><span className="text-white/40">•</span><span>{body}</span></div>
        ) : (
          <p key={i}>{body}</p>
        );
      })}
    </div>
  );
}

function proposalText(p: Record<string, unknown>): { title: string; summary: string } {
  return { title: String(p.title ?? "Proposal"), summary: p.summary ? String(p.summary) : "" };
}

export default function Transcript({ seats, messages, live, thinking, tally }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const seatOf = (letter: string) => seats.find((s) => s.letter === letter);
  const byId = new Map(messages.map((m) => [m.id, m]));

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 160;
    if (nearBottom) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages.length, live?.text]);

  const header = (letter: string, extra?: React.ReactNode) => {
    if (letter === MODERATOR) {
      return <span className="text-[12px] font-medium text-white/85">Moderator</span>;
    }
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

  return (
    <div ref={scroller} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
      {messages.length === 0 && !live && (
        <p className="pt-10 text-center text-[13px] text-white/30">The council is taking its seats…</p>
      )}
      {messages.map((m) => {
        const colour = m.seat === MODERATOR ? "#ffffff" : seatOf(m.seat)?.colour ?? "#fff";
        const target = m.reply_to ? byId.get(m.reply_to) : null;
        if (m.seat === MODERATOR) {
          return (
            <motion.div
              key={m.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              className="rounded-lg border border-white/15 bg-white/[0.04] p-3 text-[12.5px] leading-relaxed text-white/75"
            >
              <div className="mb-2 text-[10px] uppercase tracking-[0.25em] text-white/45">Moderator summary</div>
              <Markdownish text={m.content} />
            </motion.div>
          );
        }
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
                <span
                  className="rounded px-1.5 text-[10px] font-medium uppercase tracking-[0.08em]"
                  style={{ color: STANCE_COLOUR[m.stance], background: `${STANCE_COLOUR[m.stance]}14` }}
                >
                  {STANCE_LABEL[m.stance] ?? m.stance}
                  {target && (
                    <span className="normal-case tracking-normal text-white/40">
                      {" "}→ {target.seat === MODERATOR ? "moderator" : seatOf(target.seat)?.name} ({m.reply_to})
                    </span>
                  )}
                </span>,
              )}
              <span className="shrink-0 font-mono text-[10px] text-white/25">{m.id}</span>
            </div>
            <p className="text-[13px] leading-relaxed text-white/80">{m.content}</p>
            {m.proposal && (
              <div className="mt-2 rounded border px-2.5 py-1.5 text-[12px]" style={{ borderColor: `${colour}33`, background: `${colour}0d` }}>
                <span className="font-medium" style={{ color: colour }}>◆ {proposalText(m.proposal).title}</span>
                {proposalText(m.proposal).summary && <span className="text-white/60"> — {proposalText(m.proposal).summary}</span>}
                {tally[m.id] !== undefined && (
                  <span className="ml-2 font-mono text-[10.5px] text-white/50">{tally[m.id]} vote{tally[m.id] === 1 ? "" : "s"}</span>
                )}
              </div>
            )}
          </motion.div>
        );
      })}
      {live && (
        <div className="relative rounded-md bg-white/[0.04] py-2 pl-3.5 pr-3">
          <span
            className="absolute inset-y-1.5 left-0 w-[3px] animate-pulse rounded-full"
            style={{ background: live.seat === MODERATOR ? "#fff" : seatOf(live.seat)?.colour }}
          />
          <div className="mb-1">{header(live.seat)}</div>
          <p className="text-[13px] leading-relaxed text-white/70">
            {live.text || <span className="text-white/35">{thinking === live.seat ? "thinking…" : ""}</span>}
            <span className="ml-0.5 inline-block h-3.5 w-[2px] translate-y-0.5 animate-pulse bg-white/60" />
          </p>
        </div>
      )}
    </div>
  );
}
