"use client";

import { useState } from "react";
import { GROUP_NAME, THE_GROUP } from "@/lib/app";

type Props = {
  status: string;
  busy: boolean;
  atCheckpoint: boolean; // the budget card is open; it has its own buttons
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
  onSend: (text: string) => Promise<void>;
};

/** The user's seat: address the assembly, pause, stop. */
export default function BottomBar({ status, busy, atCheckpoint, onPause, onResume, onStop, onSend }: Props) {
  const active = status === "running" || status === "paused" || status === "checkpoint";
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    const t = text.trim();
    if (!t) return;
    setSending(true);
    try {
      await onSend(t);
      setText("");
    } finally {
      setSending(false);
    }
  };

  return (
    <footer className="glass relative z-30 mx-2 mb-2 flex h-16 shrink-0 items-center gap-3 rounded-2xl px-3 md:mx-3 md:mb-3 md:px-4">
      <span className="hidden h-2 w-2 shrink-0 rounded-full bg-white/80 shadow-[0_0_10px_white] md:block" title="You" />
      <form onSubmit={send} className="flex min-w-0 flex-1 items-center gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={!active || sending}
          maxLength={2000}
          placeholder={active ? `Address ${THE_GROUP}…` : `The ${GROUP_NAME} has adjourned`}
          className="glass-well h-10 min-w-0 flex-1 rounded-xl px-3.5 text-[13px] text-white outline-none placeholder:text-white/25 disabled:cursor-not-allowed"
        />
        <button
          type="submit"
          disabled={!active || sending || !text.trim()}
          className="hidden h-10 accent-button rounded-full px-4 text-[13px] font-medium disabled:opacity-25 sm:block"
        >
          Send
        </button>
      </form>
      {status === "paused" ? (
        <button
          disabled={busy || !active || atCheckpoint}
          onClick={onResume}
          className="h-10 glass-button rounded-full px-4 text-[13px] text-white/85 disabled:opacity-30"
        >
          Resume
        </button>
      ) : (
        <button
          disabled={busy || status !== "running"}
          onClick={onPause}
          className="h-10 glass-button rounded-full px-4 text-[13px] text-white/85 disabled:opacity-30"
        >
          Pause
        </button>
      )}
      <button
        disabled={busy || !active}
        onClick={onStop}
        className="h-10 rounded-lg border border-red-400/30 px-4 text-[13px] text-red-300/90 hover:border-red-400/60 disabled:opacity-30"
      >
        Stop
      </button>
    </footer>
  );
}
