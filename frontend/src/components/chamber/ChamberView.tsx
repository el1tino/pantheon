"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { AnimatePresence, useReducedMotion } from "framer-motion";
import { answerBudget, answerCheckpoint, controlRun, sendMessage } from "@/lib/api";
import { computeLayout } from "@/lib/chamber/geometry";
import { useChamber } from "@/lib/chamber/useChamber";
import BottomBar from "./BottomBar";
import Board from "./Board";
import BudgetCard from "./BudgetCard";
import CheckpointCard from "./CheckpointCard";
import Core from "./Core";
import DiffFeed from "./DiffFeed";
import Seat from "./Seat";
import TopBar from "./TopBar";
import PlanCard from "./PlanCard";
import ResultPanel from "./ResultPanel";
import Transcript from "./Transcript";
import Vault from "./Vault";

// PixiJS needs the browser.
const EffectsLayer = dynamic(() => import("./EffectsLayer"), { ssr: false });

const DECIDED_BY: Record<string, string> = {
  consensus: "consensus",
  vote: "majority vote",
  moderator: "the moderator",
  client: "you",
};

export default function ChamberView({ runId }: { runId: string }) {
  const { state, connection, subscribe } = useChamber(runId);
  const reducedMotion = useReducedMotion() ?? false;
  const stageRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [drawerOpen, setDrawerOpen] = useState(true);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [diffOpen, setDiffOpen] = useState(false);
  const [flash, setFlash] = useState<{ key: number; kind: "add" | "remove" } | null>(null);
  const [busy, setBusy] = useState(false);
  const [resultOpen, setResultOpen] = useState(false);
  const [panel, setPanelState] = useState<"board" | "vault" | null>(null);
  const panelRef = useRef<"board" | "vault" | null>(null);
  // The Board, the Vault and the result share the stage: opening one closes the others.
  const setPanel = (next: "board" | "vault" | null) => {
    panelRef.current = next;
    setPanelState(next);
    if (next) setResultOpen(false);
  };
  const shownResult = useRef<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ w: Math.round(width), h: Math.round(height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const letters = state.seats.map((s) => s.letter).join(",");
  const layout = useMemo(
    () => computeLayout(size.w, size.h, letters ? letters.split(",") : []),
    [size.w, size.h, letters],
  );

  const flashSeq = useRef(0);
  const onCoreHit = useCallback((added: number, removed: number) => {
    flashSeq.current += 1;
    setFlash({ key: flashSeq.current, kind: added >= removed ? "add" : "remove" });
  }, []);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const decision = useMemo(() => {
    if (!state.decision) return null;
    const m = state.messages.find((x) => x.id === state.decision!.id);
    if (!m) return null;
    const seat = state.seats.find((s) => s.letter === m.seat);
    // For a picked option the moderator's "chose" note carries the title.
    const picked = [...state.messages].reverse().find((x) => x.seat === "moderator" && x.round === "pick");
    const pickedTitle = picked?.content.match(/chose o\d+: (.*?)\./)?.[1];
    const title = pickedTitle ?? String(m.proposal?.title ?? m.content.slice(0, 80));
    return { title, colour: seat?.colour ?? "#fff", by: DECIDED_BY[state.decision.decidedBy] ?? state.decision.decidedBy };
  }, [state.decision, state.messages, state.seats]);

  // Open the result once when the run finishes with a deliverable.
  useEffect(() => {
    if (state.status === "done" && state.deliverable && state.caughtUp && shownResult.current !== runId) {
      shownResult.current = runId;
      // Only if the user isn't already looking at the Board or the Vault.
      const t = setTimeout(() => setResultOpen((open) => open || panelRef.current === null), 1600);
      return () => clearTimeout(t);
    }
  }, [state.status, state.deliverable, state.caughtUp, runId]);

  const thinking = state.seats.find((s) => s.status === "thinking")?.letter ?? null;
  const dim = !!state.checkpoint;
  const finished = ["done", "stopped", "failed"].includes(state.status);

  const transcript = (
    <>
      <div className="flex h-11 shrink-0 items-center gap-1 border-b border-white/[0.06] px-3">
        {([
          ["transcript", "Transcript", null],
          ["board", "Board", Object.values(state.tasks).filter((t) => t.kind !== "workstream").length],
          ["vault", "Vault", Object.keys(state.files).length],
        ] as const).map(([key, label, count]) => {
          const active = key === "transcript" ? panel === null : panel === key;
          return (
            <button
              key={key}
              onClick={() => setPanel(key === "transcript" ? null : panel === key ? null : key)}
              className={`rounded-md px-2.5 py-1 text-[12px] transition-colors ${active ? "bg-white/[0.08] text-white/90" : "text-white/45 hover:text-white/80"}`}
            >
              {label}
              {count ? <span className="ml-1.5 font-mono text-[10px] text-white/35">{count}</span> : null}
            </button>
          );
        })}
        <button
          onClick={() => (window.innerWidth < 768 ? setSheetOpen(false) : setDrawerOpen(false))}
          className="ml-auto rounded px-2 py-1 text-[12px] text-white/40 hover:text-white"
          aria-label="Collapse transcript"
        >
          {"⟩"}
        </button>
      </div>
      <Transcript seats={state.seats} messages={state.messages} live={state.live} thinking={thinking} tally={state.tally} scores={state.scores} />
    </>
  );

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <TopBar
        goal={state.goal}
        mission={state.mission?.label ?? null}
        phases={state.phases}
        phase={state.phase}
        round={state.round}
        maxRounds={state.maxRounds}
        status={state.status}
        spent={state.cost.spent}
        cap={state.cost.cap}
      />

      <div className="relative flex min-h-0 flex-1">
        <div
          ref={stageRef}
          className="chamber-stage relative min-w-0 flex-1 overflow-hidden"
        >
          {size.w > 0 && state.ready && (
            <div className={`absolute inset-0 transition-[opacity,filter] duration-700 ${dim ? "opacity-40 blur-[1px]" : ""}`}>
              {state.seats.map((seat, i) => (
                <Seat
                  key={seat.letter}
                  seat={seat}
                  spot={layout.seats[i]}
                  compact={layout.compact}
                  reducedMotion={reducedMotion}
                />
              ))}
              <Core
                x={layout.core.x}
                y={layout.core.y}
                width={layout.core.w}
                plus={state.core.plus}
                minus={state.core.minus}
                flash={flash}
                decision={finished ? decision : null}
                onOpen={() => setDiffOpen((v) => !v)}
                reducedMotion={reducedMotion}
              />
              <EffectsLayer
                layout={layout}
                seats={state.seats}
                heat={state.heat}
                subscribe={subscribe}
                onCoreHit={onCoreHit}
                reducedMotion={reducedMotion}
                stageRef={stageRef}
              />
            </div>
          )}

          {!state.ready && (
            <div className="absolute inset-0 flex items-center justify-center text-[13px] text-white/35">
              {connection === "closed" ? "Can't reach the council. Is the backend running on port 8000?" : "Convening the council…"}
            </div>
          )}

          {(state.status === "failed" || state.error || actionError) && (
            <div className="absolute left-1/2 top-4 z-40 -translate-x-1/2 rounded-md border border-red-400/30 bg-red-950/60 px-3 py-1.5 text-[12px] text-red-200">
              {actionError ?? state.error ?? "The run failed."}
            </div>
          )}
          {state.status === "stopped" && (
            <div className="absolute left-1/2 top-4 z-40 -translate-x-1/2 rounded-md border border-white/15 bg-black/60 px-3 py-1.5 text-[12px] text-white/70">
              The run was stopped.
            </div>
          )}

          {!drawerOpen && (
            <button
              onClick={() => setDrawerOpen(true)}
              className="absolute right-3 top-3 z-40 hidden rounded-md border border-white/10 bg-black/50 px-2.5 py-1 text-[12px] text-white/60 hover:text-white md:block"
            >
              {"⟨"} Transcript
            </button>
          )}
          <button
            onClick={() => setSheetOpen(true)}
            className="absolute bottom-3 left-1/2 z-40 -translate-x-1/2 rounded-full border border-white/10 bg-black/60 px-4 py-1.5 text-[12px] text-white/70 md:hidden"
          >
            Transcript · {state.messages.length}
          </button>

          <AnimatePresence>
            {diffOpen && <DiffFeed diffs={state.diffs} seats={state.seats} onClose={() => setDiffOpen(false)} />}
          </AnimatePresence>

          {state.deliverable && !resultOpen && !state.checkpoint && (
            <button
              onClick={() => {
                setPanel(null);
                setResultOpen(true);
              }}
              className="absolute bottom-4 right-4 z-40 rounded-full border border-amber-200/30 bg-black/60 px-4 py-1.5 text-[12px] text-amber-100/90 shadow-[0_0_24px_rgba(253,230,138,0.12)] hover:border-amber-200/60"
            >
              View result · {state.deliverable.title}
            </button>
          )}
          <AnimatePresence>
            {panel === "board" && <Board tasks={state.tasks} seats={state.seats} onClose={() => setPanel(null)} />}
            {panel === "vault" && (
              <Vault runId={runId} files={state.files} seats={state.seats} siteVersion={state.siteVersion} onClose={() => setPanel(null)} />
            )}
          </AnimatePresence>
          <AnimatePresence>
            {resultOpen && state.deliverable && (
              <ResultPanel runId={runId} deliverable={state.deliverable} onClose={() => setResultOpen(false)} />
            )}
          </AnimatePresence>

          {(state.checkpoint?.kind === "pick" || state.checkpoint?.kind === "review") && (
            <CheckpointCard
              key={`${state.checkpoint.kind}-${state.lastSeq}`}
              checkpoint={state.checkpoint}
              seats={state.seats}
              runId={runId}
              siteVersion={state.siteVersion}
              onAnswer={async (answer) => {
                await answerCheckpoint(runId, answer);
              }}
            />
          )}
          {state.checkpoint?.kind === "plan" && (
            <PlanCard
              key={`plan-${state.lastSeq}`}
              checkpoint={state.checkpoint}
              seats={state.seats}
              onApprove={async (assignments) => {
                await answerCheckpoint(runId, { action: "approve", assignments });
              }}
            />
          )}

          {state.checkpoint?.kind === "budget" && (
            <BudgetCard
              spent={state.checkpoint.spent}
              cap={state.checkpoint.cap}
              estimate={state.checkpoint.estimate}
              onRaise={async (cap) => {
                await answerBudget(runId, "raise", cap);
              }}
              onStop={async () => {
                await answerBudget(runId, "stop");
              }}
            />
          )}
        </div>

        {/* Desktop drawer */}
        <aside
          className={`relative z-30 hidden shrink-0 flex-col border-l border-white/[0.06] bg-black/35 backdrop-blur transition-[width] duration-500 ease-out md:flex ${
            drawerOpen ? "w-[380px] xl:w-[420px]" : "w-0 overflow-hidden border-l-0"
          }`}
        >
          {drawerOpen && transcript}
        </aside>

        {/* Mobile bottom sheet */}
        <aside
          className={`fixed inset-x-0 bottom-16 z-40 flex h-[62dvh] flex-col rounded-t-2xl border-t border-white/10 bg-[#0a0a0d]/95 backdrop-blur transition-transform duration-500 ease-out md:hidden ${
            sheetOpen ? "translate-y-0" : "translate-y-[calc(100%+4rem)]"
          }`}
        >
          {transcript}
        </aside>
      </div>

      <BottomBar
        status={state.status}
        busy={busy}
        atCheckpoint={state.checkpoint?.kind === "budget"}
        onSend={async (text) => {
          setActionError(null);
          try {
            await sendMessage(runId, text);
          } catch (e) {
            setActionError(e instanceof Error ? e.message : String(e));
          }
        }}
        onPause={() => act(() => controlRun(runId, "pause"))}
        onResume={() => act(() => controlRun(runId, "resume"))}
        onStop={() => act(() => controlRun(runId, "stop"))}
      />
    </div>
  );
}
