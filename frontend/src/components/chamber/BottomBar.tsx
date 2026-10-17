"use client";

type Props = {
  status: string;
  busy: boolean;
  atCheckpoint: boolean; // the budget card is open; it has its own buttons
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
};

/** The user's seat. Addressing the council arrives with checkpoints; pause and stop work now. */
export default function BottomBar({ status, busy, atCheckpoint, onPause, onResume, onStop }: Props) {
  const active = status === "running" || status === "paused";
  return (
    <footer className="relative z-30 flex h-16 shrink-0 items-center gap-3 border-t border-white/[0.06] bg-black/30 px-4 backdrop-blur md:px-6">
      <span className="hidden h-2 w-2 shrink-0 rounded-full bg-white/80 shadow-[0_0_10px_white] md:block" title="You" />
      <input
        disabled
        placeholder="Address the council (coming soon)"
        className="h-10 min-w-0 flex-1 rounded-lg border border-white/10 bg-white/[0.03] px-3 text-[13px] text-white placeholder:text-white/25 disabled:cursor-not-allowed"
      />
      {status === "paused" ? (
        <button
          disabled={busy || !active || atCheckpoint}
          onClick={onResume}
          className="h-10 rounded-lg border border-white/15 px-4 text-[13px] text-white/85 hover:border-white/35 disabled:opacity-30"
        >
          Resume
        </button>
      ) : (
        <button
          disabled={busy || !active}
          onClick={onPause}
          className="h-10 rounded-lg border border-white/15 px-4 text-[13px] text-white/85 hover:border-white/35 disabled:opacity-30"
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
