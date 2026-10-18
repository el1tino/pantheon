// Turns the run's event stream into what the Chamber shows. Pure, so live runs,
// late joiners and (later) Replay all go through the same code.

import {
  CLIENT, ChamberEvent, CheckView, Checkpoint, Deliverable, Diff, FileView, ImageView, MODERATOR, Message,
  RailPhase, SeatInfo, TaskView,
} from "./types";

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
  live: Record<string, string>; // seat -> text streaming right now (several during the build)
  cost: { spent: number; cap: number; ratio: number; warning: boolean };
  core: { plus: number; minus: number };
  diffs: Diff[];
  checkpoint: Checkpoint | null;
  decision: { id: string; decidedBy: string } | null;
  tally: Record<string, number>;
  scores: Record<string, number[]>; // option id -> anonymous 1-5 scores
  mission: { key: string; label: string; reason: string } | null;
  phases: RailPhase[];
  deliverable: Deliverable | null;
  tasks: Record<string, TaskView>;
  files: Record<string, FileView>;
  siteVersion: number; // bumps whenever a file under site/ changes, to refresh the preview
  images: ImageView[];
  checks: CheckView[];
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
  live: {},
  cost: { spent: 0, cap: 0, ratio: 0, warning: false },
  core: { plus: 0, minus: 0 },
  diffs: [],
  checkpoint: null,
  decision: null,
  tally: {},
  scores: {},
  mission: null,
  phases: [{ key: "convene", label: "Convene", available: true }],
  deliverable: null,
  tasks: {},
  files: {},
  siteVersion: 0,
  images: [],
  checks: [],
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

// Whoever starts thinking or talking takes the floor from seats that have finished speaking.
// Seats still streaming (parallel builders) keep theirs.
function takeFloor(seats: SeatView[], letter: string, live: Record<string, string>): SeatView[] {
  return seats.map((s) =>
    s.letter !== letter && !(s.letter in live) && (s.status === "speaking" || s.status === "thinking")
      ? { ...s, status: "idle" }
      : s,
  );
}

function without(live: Record<string, string>, seat: string): Record<string, string> {
  if (!(seat in live)) return live;
  const next = { ...live };
  delete next[seat];
  return next;
}

// A seat's badge shows the role the council voted it into: the workstreams it leads, or
// in lighter missions the parts it writes.
function badges(seats: SeatView[], tasks: Record<string, TaskView>): SeatView[] {
  const all = Object.values(tasks);
  const leads = all.filter((t) => t.kind === "workstream");
  const source = leads.length ? leads : all.filter((t) => t.kind === "part");
  return seats.map((seat) => {
    const mine = source.filter((t) => t.owner === seat.letter).map((t) => t.title);
    const role = mine.length ? (mine.length > 1 ? `${mine[0]} +${mine.length - 1}` : mine[0]) : null;
    return seat.role === role ? seat : { ...seat, role };
  });
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
      if (p.mission) {
        s.mission = { key: p.mission, label: p.mission_label ?? p.mission, reason: p.reason ?? "" };
      }
      if (p.phases) s.phases = p.phases as RailPhase[];
      if (p.phase) s.phase = p.phase;
      if ("round" in p) s.round = p.round;
      if (p.status) s.status = p.status;
      if (p.error) s.error = p.error;
      if (p.decision !== undefined && p.status) {
        s.decision = p.decision ? { id: p.decision, decidedBy: p.decided_by } : null;
        s.live = {};
        s.seats = s.seats.map((x) => (x.status === "absent" ? x : { ...x, status: "idle" }));
      }
      return s;
    }
    case "seat_thinking": {
      if (p.state === "absent") {
        s.seats = updateSeat(s.seats, p.seat, { status: "absent", caption: "", error: p.error });
        s.live = without(s.live, p.seat);
        return s;
      }
      if (p.state === "thinking" || p.state === "retrying") {
        s.seats = updateSeat(takeFloor(s.seats, p.seat, s.live), p.seat, {
          status: "thinking",
          caption: "",
        });
        s.live = { ...s.live, [p.seat]: "" };
      }
      return s;
    }
    case "token": {
      const text = (s.live[p.seat] ?? "") + p.text;
      s.live = { ...s.live, [p.seat]: text };
      s.seats = updateSeat(takeFloor(s.seats, p.seat, s.live), p.seat, {
        status: "speaking",
        caption: firstLine(text),
      });
      return s;
    }
    case "message_done": {
      if (p.dropped) {
        s.seats = updateSeat(s.seats, p.seat, { status: "idle", caption: "" });
        s.live = without(s.live, p.seat);
        return s;
      }
      const msg = p as unknown as Message;
      s.messages = [...s.messages, msg];
      if (msg.seat === CLIENT) return s; // the user's words don't interrupt whoever is speaking
      s.live = without(s.live, msg.seat);
      if (msg.seat !== MODERATOR) {
        s.seats = updateSeat(takeFloor(s.seats, msg.seat, s.live), msg.seat, {
          status: "speaking",
          caption: firstLine(msg.content),
        });
      }
      return s;
    }
    case "message_routed": {
      const to = p.to as string;
      if (to !== "all" && p.from !== MODERATOR && p.from !== CLIENT && (p.stance === "agree" || p.stance === "challenge")) {
        const key = pairKey(p.from, to);
        const h = s.heat[key] ?? { agree: 0, challenge: 0 };
        s.heat = { ...s.heat, [key]: { ...h, [p.stance]: h[p.stance as "agree" | "challenge"] + 1 } };
      }
      return s;
    }
    case "vote_cast":
      if (p.kind === "score") {
        s.scores = { ...s.scores, [p.target]: [...(s.scores[p.target] ?? []), p.score] };
      } else if (p.kind !== "role") {
        s.tally = { ...s.tally, [p.target]: (s.tally[p.target] ?? 0) + (p.score ?? 1) };
      }
      return s;
    case "task_updated": {
      const prev = s.tasks[p.part];
      s.tasks = {
        ...s.tasks,
        [p.part]: {
          id: p.part,
          kind: p.kind ?? "part",
          title: p.title,
          owner: p.owner_seat ?? null,
          reviewer: p.reviewer_seat ?? prev?.reviewer ?? null,
          status: p.status,
          files: p.files ?? prev?.files ?? [],
          dependsOn: p.depends_on ?? prev?.dependsOn ?? [],
          workstream: p.workstream ?? prev?.workstream ?? null,
          question: p.question ?? prev?.question ?? null,
        },
      };
      s.seats = badges(s.seats, s.tasks);
      return s;
    }
    case "artifact_created":
      if (p.kind === "deliverable") s.deliverable = { title: p.title, content: p.content, path: p.path };
      if (p.kind === "image") {
        const prev = s.images.find((i) => i.path === p.path);
        const img: ImageView = {
          path: p.path, kind: p.image_kind, consultant: p.consultant, prompt: p.prompt, seat: p.seat,
          version: (prev?.version ?? 0) + 1,
        };
        s.images = [...s.images.filter((i) => i.path !== p.path), img];
        s.siteVersion += 1;
      }
      if (p.kind === "check") {
        s.checks = [...s.checks, { path: p.path, status: p.status, errors: p.errors, warnings: p.warnings, detail: p.detail ?? "" }];
      }
      return s;
    case "cost_updated":
      s.cost = { spent: p.spent_usd, cap: p.cap_usd, ratio: p.ratio, warning: p.warning };
      return s;
    case "checkpoint_opened":
      if (p.kind === "budget") {
        s.checkpoint = { kind: "budget", spent: p.spent_usd, cap: p.cap_usd, estimate: p.next_call_estimate_usd };
        s.status = "paused";
      } else {
        s.checkpoint = p as unknown as Checkpoint;
        s.status = "checkpoint";
        s.live = {};
        s.seats = s.seats.map((x) => (x.status === "absent" ? x : { ...x, status: "idle" }));
      }
      return s;
    case "checkpoint_resolved":
      s.checkpoint = null;
      if (p.kind !== "budget" && p.action !== "stop") s.status = "running";
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
      const f = s.files[p.file];
      s.files = {
        ...s.files,
        [p.file]: {
          seat: p.seat,
          versions: (f?.versions ?? 0) + 1,
          added: (f?.added ?? 0) + p.lines_added,
          removed: (f?.removed ?? 0) + p.lines_removed,
        },
      };
      if (String(p.file).startsWith("site/")) s.siteVersion += 1;
      return s;
    }
    default:
      return s;
  }
}
