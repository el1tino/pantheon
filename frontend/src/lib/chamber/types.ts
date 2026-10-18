// Mirrors the backend event log (backend/app/orchestrator/debate.py).

export type Stance = "propose" | "challenge" | "agree" | "vote" | "report" | "question";

export type SeatInfo = {
  letter: string;
  name: string;
  colour: string;
  logo?: string; // provider logo in /logos/, set in config/seats.yaml; older runs have none
  role: string | null; // assumed role, voted on by the council; none until then
  model_id: string;
};

export type ChamberEvent = {
  seq: number;
  type: string;
  payload: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
};

export type Message = {
  id: string;
  seat: string; // letter or "moderator"
  round: number | string;
  stance: Stance;
  reply_to: string | null;
  content: string;
  proposal: Record<string, unknown> | null;
  votes: { target: string; score: number }[] | null;
  cost_usd: number;
  unverified?: boolean; // claimed success without pointing at proof
};

export type ImageView = { path: string; kind: string; consultant: string; prompt: string; seat: string; version: number };

export type CheckView = {
  path: string;
  status: "passed" | "failed" | "not_run";
  errors: number;
  warnings: number;
  detail: string;
};

export type DiffLine = { op: "+" | "-"; text: string };

export type Diff = {
  seq: number;
  seat: string;
  file: string;
  added: number;
  removed: number;
  lines: DiffLine[];
};

export const MODERATOR = "moderator";
export const CLIENT = "client"; // the user, addressing the council

export type RailPhase = { key: string; label: string; available: boolean };

export type PickOption = {
  id: string;
  title: string;
  summary: string;
  seat: string;
  score: number;
  votes: number;
};

export type PlanTask = {
  id: string;
  title: string;
  workstream: string;
  brief: string;
  files: string[];
  depends_on: string[];
  owner: string | null;
  reviewer: string | null;
};

export type PlanWorkstream = { id: string; title: string; brief: string; lead: string | null; votes: number };

export type Checkpoint =
  | { kind: "budget"; spent: number; cap: number; estimate: number }
  | { kind: "pick"; phase: string; options: PickOption[]; can_retry: boolean }
  | {
      kind: "review";
      phase: string;
      title: string;
      content: string;
      path: string;
      preview?: string | null;
      files?: string[];
      images?: { path: string; kind: string; prompt: string; consultant: string; seat: string }[];
      check?: { path: string; status: string; errors: unknown[] } | null;
    }
  | { kind: "plan"; phase: string; workstreams: PlanWorkstream[]; tasks: PlanTask[]; seats: string[] };

export type TaskView = {
  id: string;
  kind: "task" | "workstream" | "part";
  title: string;
  owner: string | null;
  reviewer: string | null;
  status: string;
  files: string[];
  dependsOn: string[];
  workstream: string | null;
  question: { to: string; text: string; answer?: string } | null;
};

export type FileView = { seat: string; versions: number; added: number; removed: number };

export type Deliverable = { title: string; content: string; path: string };


export const STANCE_LABEL: Record<string, string> = {
  propose: "Proposes",
  challenge: "Challenges",
  agree: "Agrees",
  vote: "Votes",
  report: "Reports",
  question: "Asks",
};

// Line styles from the spec: white proposal, green agreement, red challenge, dotted question.
export const STANCE_COLOUR: Record<string, string> = {
  propose: "#f4f1ea",
  agree: "#34d399",
  challenge: "#f87171",
  question: "#cbd5e1",
  vote: "#f4f1ea",
  report: "#f4f1ea",
};
