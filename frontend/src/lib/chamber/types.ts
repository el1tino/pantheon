// Mirrors the backend event log (backend/app/orchestrator/debate.py).

export type Stance = "propose" | "challenge" | "agree" | "vote" | "report" | "question";

export type SeatInfo = {
  letter: string;
  name: string;
  colour: string;
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

export type Checkpoint =
  | { kind: "budget"; spent: number; cap: number; estimate: number }
  | { kind: "pick"; phase: string; options: PickOption[]; can_retry: boolean }
  | { kind: "review"; phase: string; title: string; content: string; path: string };

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
