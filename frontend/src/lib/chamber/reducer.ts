// Turns the run's event stream into what the Chamber shows. Pure, so live runs,
// late joiners and (later) Replay all go through the same code.

import { ChamberEvent, Diff, MODERATOR, Message, SeatInfo } from "./types";

export type SeatStatus = "idle" | "thinking" | "speaking" | "absent";

export type SeatView = SeatInfo & {
  status: SeatStatus;
  caption: string;
  plus: number;
  minus: number;
  error?: string;
};

export type Heat = Record<string, { agree: number; challenge: number }>;

export type ChamberState = {
  ready: boolean;
  caughtUp: boolean;
  goal: string;
  phase: string;
  round: number | string | null;
  maxRounds: number;
  status: string;
  seats: SeatView[];
  messages: Message[];
  live: { seat: string; text: string } | null;
  cost: { spent: number; cap: number; ratio: number; warning: boolean };
  core: { plus: number; minus: number };
  diffs: Diff[];
  checkpoint: { kind: string; spent: number; cap: number; estimate: number } | null;
  decision: { id: string; decidedBy: string } | null;
  tally: Record<string, number>;
  heat: Heat;
  error: string | null;
  lastSeq: number;
};

export const initialState: ChamberState = {
  ready: false,
  caughtUp: false,
  goal: "",
  phase: "convene",
  round: null,
  maxRounds: 3,
  status: "created",
  seats: [],
  messages: [],
  live: null,
  cost: { spent: 0, cap: 0, ratio: 0, warning: false },
  core: { plus: 0, minus: 0 },
  diffs: [],
  checkpoint: null,
  decision: null,
  tally: {},
  heat: {},
  error: null,
  lastSeq: 0,
};

const MAX_DIFFS = 400;

export function pairKey(a: string, b: string): string {
  return a < b ? `${a}|${b}` : `${b}|${a}`;
}

export function firstLine(text: string): string {
  const line = text.split("\n").find((l) => l.trim()) ?? "";
  return line.trim();
}

function updateSeat(seats: SeatView[], letter: string, patch: Partial<SeatView>): SeatView[] {
  return seats.map((s) => (s.letter === letter ? { ...s, ...patch } : s));
}

// Only one seat speaks at a time: whoever starts thinking or talking takes the floor.
function takeFloor(seats: SeatView[], letter: string): SeatView[] {
  return seats.map((s) =>
    s.letter !== letter && (s.status === "speaking" || s.status === "thinking")
      ? { ...s, status: "idle" }
      : s,
  );
}

export function reduce(state: ChamberState, ev: ChamberEvent): ChamberState {
  if (ev.type === "caught_up") return { ...state, caughtUp: true };
  if (ev.seq <= state.lastSeq) return state; // already applied
  const p = ev.payload;
  const s: ChamberState = { ...state, lastSeq: ev.seq };

  switch (ev.type) {
    case "phase_changed": {
      if (p.seats) {
        s.ready = true;
        s.goal = p.goal ?? s.goal;
        s.maxRounds = p.max_rounds ?? s.maxRounds;
        s.cost = { ...s.cost, cap: p.budget_usd ?? s.cost.cap };
        s.seats = (p.seats as SeatInfo[]).map((x) => ({
          ...x, status: "idle", caption: "", plus: 0, minus: 0,
        }));
        s.status = "running";
      }
      if (p.phase) s.phase = p.phase;
      if ("round" in p) s.round = p.round;
      if (p.status) s.status = p.status;
      if (p.error) s.error = p.error;
      if (p.decision !== undefined && p.status) {
        s.decision = p.decision ? { id: p.decision, decidedBy: p.decided_by } : null;
        s.live = null;
        s.seats = s.seats.map((x) => (x.status === "absent" ? x : { ...x, status: "idle" }));
      }
      return s;
    }
    case "seat_thinking": {
      if (p.state === "absent") {
        s.seats = updateSeat(s.seats, p.seat, { status: "absent", caption: "", error: p.error });
        if (s.live?.seat === p.seat) s.live = null;
        return s;
      }
      if (p.state === "thinking" || p.state === "retrying") {
        s.seats = updateSeat(takeFloor(s.seats, p.seat), p.seat, {
          status: "thinking",
          caption: "",
        });
        s.live = { seat: p.seat, text: "" };
      }
      return s;
    }
    case "token": {
      const text = (s.live && s.live.seat === p.seat ? s.live.text : "") + p.text;
      s.live = { seat: p.seat, text };
      s.seats = updateSeat(takeFloor(s.seats, p.seat), p.seat, {
        status: "speaking",
        caption: firstLine(text),
      });
      return s;
    }
    case "message_done": {
      if (p.dropped) {
        s.seats = updateSeat(s.seats, p.seat, { status: "idle", caption: "" });
        s.live = null;
        return s;
      }
      const msg = p as unknown as Message;
      s.messages = [...s.messages, msg];
      s.live = null;
      if (msg.seat !== MODERATOR) {
        s.seats = updateSeat(takeFloor(s.seats, msg.seat), msg.seat, {
          status: "speaking",
          caption: firstLine(msg.content),
        });
      }
      return s;
    }
    case "message_routed": {
      const to = p.to as string;
      if (to !== "all" && p.from !== MODERATOR && (p.stance === "agree" || p.stance === "challenge")) {
        const key = pairKey(p.from, to);
        const h = s.heat[key] ?? { agree: 0, challenge: 0 };
        s.heat = { ...s.heat, [key]: { ...h, [p.stance]: h[p.stance as "agree" | "challenge"] + 1 } };
      }
      return s;
    }
    case "vote_cast":
      s.tally = { ...s.tally, [p.target]: (s.tally[p.target] ?? 0) + (p.score ?? 1) };
      return s;
    case "cost_updated":
      s.cost = { spent: p.spent_usd, cap: p.cap_usd, ratio: p.ratio, warning: p.warning };
      return s;
    case "checkpoint_opened":
      s.checkpoint = {
        kind: p.kind,
        spent: p.spent_usd,
        cap: p.cap_usd,
        estimate: p.next_call_estimate_usd,
      };
      s.status = "paused";
      return s;
    case "checkpoint_resolved":
      s.checkpoint = null;
      if (p.action === "raise_cap") {
        s.cost = { ...s.cost, cap: p.cap_usd, ratio: s.cost.spent / p.cap_usd, warning: s.cost.spent / p.cap_usd >= 0.8 };
        s.status = "running";
      }
      return s;
    case "diff_applied": {
      s.core = { plus: s.core.plus + p.lines_added, minus: s.core.minus + p.lines_removed };
      const seat = s.seats.find((x) => x.letter === p.seat);
      if (seat) {
        s.seats = updateSeat(s.seats, p.seat, {
          plus: seat.plus + p.lines_added,
          minus: seat.minus + p.lines_removed,
        });
      }
      const diff: Diff = {
        seq: ev.seq, seat: p.seat, file: p.file, added: p.lines_added,
        removed: p.lines_removed, lines: p.lines ?? [],
      };
      s.diffs = [...s.diffs, diff].slice(-MAX_DIFFS);
      return s;
    }
    default:
      return s;
  }
}
