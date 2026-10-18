"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { APP_NAME } from "@/lib/app";
import DemoList from "@/components/DemoList";
import {
  HttpError, MissionOption, RunSummary, SeatOption, User, createInvite, createRun, goToLogin, listMissions, listRuns,
  listSeats, logout, me, publicConfig,
} from "@/lib/api";

const DEFAULT_SEATS = ["A", "B", "C", "D"];

const EXAMPLES: Record<string, string> = {
  auto: "Anything you'd ask an AI: a question, an email, a trip, a decision, a topic to learn…",
  ask: "Is it worth paying off my student loan early, or should I invest instead?",
  write: "Write a warm but firm email asking my landlord to fix the heating this week.",
  plan: "Plan a 3-day trip to Lisbon in May for two people, mid-range budget.",
  decide: "Should I buy a Kindle Paperwhite or a Kobo Clara?",
  learn: "Help me understand how compound interest works, for a test on Friday.",
  launch: "Come up with a business idea we could launch in a month, and name it.",
};

/** Who's logged in, a log-out link and, for the owner, invite links. */
function AccountBar({ user }: { user: User }) {
  const [link, setLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const invite = async () => {
    setError(null);
    try {
      const { path } = await createInvite();
      setLink(window.location.origin + path);
      setCopied(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <div className="mb-8 flex flex-col items-end gap-2 text-[12px] text-white/45">
      <div className="flex items-center gap-4">
        <span className="truncate">{user.email}</span>
        {user.is_owner && (
          <button onClick={invite} className="text-amber-100/80 hover:text-amber-100">Invite someone</button>
        )}
        <button
          onClick={async () => {
            await logout().catch(() => {});
            window.location.assign("/login");
          }}
          className="hover:text-white"
        >
          Log out
        </button>
      </div>
      {link && (
        <div className="flex w-full max-w-md items-center gap-2 rounded-lg border border-amber-200/20 bg-amber-200/[0.04] p-2">
          <input readOnly value={link} onFocus={(e) => e.target.select()} className="min-w-0 flex-1 bg-transparent font-mono text-[11px] text-white/75 outline-none" />
          <button
            onClick={async () => {
              await navigator.clipboard?.writeText(link).catch(() => {});
              setCopied(true);
            }}
            className="shrink-0 rounded-md bg-white/[0.08] px-2.5 py-1 text-white/80 hover:bg-white/[0.14]"
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      )}
      {link && <span className="text-[11px] text-white/30">One person, one use, expires in a week.</span>}
      {error && <span className="text-red-300">{error}</span>}
    </div>
  );
}

/** DEMO_MODE: a public link that only plays the recorded demo. */
function DemoScreen() {
  return (
    <main className="chamber-stage flex min-h-dvh flex-col items-center px-4 py-16 md:py-24">
      <div className="w-full max-w-md">
        <p className="text-center text-[13px] font-semibold uppercase tracking-[0.5em] text-white/80">{APP_NAME}</p>
        <p className="mt-3 text-center text-2xl font-medium tracking-tight text-white">A council of AI models, at work</p>
        <p className="mt-3 text-center text-[13px] leading-relaxed text-white/45">
          Models from different providers debate a goal, vote on who does what and build the result. This is a
          recorded run made with the built-in practice council, so its replies are scripted. New runs are
          switched off here.
        </p>
        <DemoList className="mt-10" />
      </div>
    </main>
  );
}

export default function ConveneForm() {
  const [gate, setGate] = useState<"loading" | "demo" | "offline" | User>("loading");
  useEffect(() => {
    publicConfig()
      .then((cfg) => (cfg.demo_mode ? setGate("demo") : me().then(setGate)))
      .catch((e) => {
        if (e instanceof HttpError && e.status === 401) goToLogin();
        else setGate("offline");
      });
  }, []);
  if (gate === "loading") return <main className="chamber-stage min-h-dvh" />;
  if (gate === "offline") {
    return (
      <main className="chamber-stage flex min-h-dvh flex-col items-center justify-center px-4 text-center">
        <p className="text-[13px] font-semibold uppercase tracking-[0.5em] text-white/80">{APP_NAME}</p>
        <p className="mt-4 text-[15px] text-white/75">Can&apos;t reach the council.</p>
        <p className="mt-2 text-[13px] text-white/40">Is the backend running? Locally it listens on port 8000.</p>
        <button onClick={() => window.location.reload()} className="mt-6 text-[13px] text-amber-100/80 hover:text-amber-100">
          Try again
        </button>
      </main>
    );
  }
  if (gate === "demo") return <DemoScreen />;
  return <Convene user={gate} />;
}

function Convene({ user }: { user: User }) {
  const router = useRouter();
  const [seats, setSeats] = useState<SeatOption[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [picked, setPicked] = useState<string[]>(DEFAULT_SEATS);
  const [missions, setMissions] = useState<MissionOption[]>([]);
  const [mission, setMission] = useState("auto");
  const [goal, setGoal] = useState("");
  const [rounds, setRounds] = useState(3);
  const [budget, setBudget] = useState("0.25");
  const [cheap, setCheap] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listSeats().then(setSeats).catch((e) => setError(`Can't reach the backend: ${e.message}`));
    listRuns().then(setRuns).catch(() => {});
    listMissions().then(setMissions).catch(() => {});
  }, []);

  const toggle = (letter: string) =>
    setPicked((p) => (p.includes(letter) ? p.filter((x) => x !== letter) : [...p, letter].sort()));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { run_id } = await createRun({
        goal: goal.trim(), seats: picked, budget_usd: Number(budget), max_rounds: rounds, cheap, mission,
      });
      router.push(`/chamber/${run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  return (
    <main className="chamber-stage min-h-dvh px-5 py-12 md:py-20">
      <div className="mx-auto max-w-3xl">
        <AccountBar user={user} />
        <motion.h1
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7 }}
          className="text-center text-[13px] font-semibold uppercase tracking-[0.5em] text-white/80"
        >
          {APP_NAME}
        </motion.h1>
        <p className="mt-3 text-center text-2xl font-medium tracking-tight text-white md:text-3xl">Convene the council</p>

        <form onSubmit={submit} className="mt-10 space-y-8">
          <div>
            <span className="mb-2 block text-[11px] uppercase tracking-[0.2em] text-white/40">Mission</span>
            <div className="flex flex-wrap gap-2">
              {[{ key: "auto", label: "Auto", tagline: "The moderator reads your goal and picks", available: true }, ...missions].map((m) => {
                const on = mission === m.key;
                return (
                  <button
                    type="button"
                    key={m.key}
                    disabled={!m.available}
                    onClick={() => setMission(m.key)}
                    aria-pressed={on}
                    title={m.available ? m.tagline : `${m.tagline} (coming soon)`}
                    className={`rounded-full border px-3.5 py-1.5 text-[13px] transition-all duration-300 ${
                      on
                        ? "border-amber-200/60 bg-amber-200/10 text-amber-100 shadow-[0_0_20px_rgba(253,230,138,0.12)]"
                        : m.available
                          ? "border-white/10 text-white/60 hover:border-white/25 hover:text-white/85"
                          : "cursor-not-allowed border-white/[0.05] text-white/20"
                    }`}
                  >
                    {m.label}
                    {!m.available && <span className="ml-1.5 text-[10px] uppercase tracking-wider">soon</span>}
                  </button>
                );
              })}
            </div>
            <p className="mt-2 text-[12px] text-white/35">
              {mission === "auto"
                ? "The moderator reads your goal, picks the mission and says why."
                : missions.find((m) => m.key === mission)?.tagline}
            </p>
          </div>

          <label className="block">
            <span className="mb-2 block text-[11px] uppercase tracking-[0.2em] text-white/40">The goal</span>
            <textarea
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder={EXAMPLES[mission] ?? EXAMPLES.auto}
              rows={3}
              className="w-full resize-y rounded-xl border border-white/10 bg-white/[0.03] p-4 text-[15px] leading-relaxed text-white outline-none transition-colors placeholder:text-white/25 focus:border-white/30"
            />
          </label>

          <div>
            <div className="mb-3 flex items-baseline justify-between">
              <span className="text-[11px] uppercase tracking-[0.2em] text-white/40">Seats · {picked.length} of {seats.length || 13}</span>
              <span className="text-[11px] text-white/30">Pick who attends</span>
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
              {seats.map((s) => {
                const on = picked.includes(s.letter);
                return (
                  <button
                    type="button"
                    key={s.letter}
                    onClick={() => toggle(s.letter)}
                    aria-pressed={on}
                    className="group flex items-center gap-3 rounded-lg border px-3 py-2 text-left transition-all duration-300"
                    style={{
                      borderColor: on ? `${s.colour}66` : "rgba(255,255,255,0.07)",
                      background: on ? `${s.colour}10` : "transparent",
                      boxShadow: on ? `0 0 22px ${s.colour}1a` : "none",
                    }}
                  >
                    <span
                      className="text-2xl font-semibold leading-none transition-opacity"
                      style={{ color: s.colour, opacity: on ? 1 : 0.35, textShadow: on ? `0 0 14px ${s.colour}88` : "none" }}
                    >
                      {s.letter}
                    </span>
                    <span className="min-w-0">
                      <span className={`block text-[13px] ${on ? "text-white/90" : "text-white/45"}`}>{s.name}</span>
                      <span className="block truncate text-[10.5px] text-white/35">{s.provider}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex flex-wrap items-end gap-6">
            <label className="block">
              <span className="mb-2 block text-[11px] uppercase tracking-[0.2em] text-white/40">Rounds</span>
              <select
                value={rounds}
                onChange={(e) => setRounds(Number(e.target.value))}
                className="h-10 rounded-lg border border-white/10 bg-[#0d0d11] px-3 text-[14px] text-white outline-none"
              >
                {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="mb-2 block text-[11px] uppercase tracking-[0.2em] text-white/40">Budget cap</span>
              <span className="flex h-10 items-center rounded-lg border border-white/10 bg-white/[0.03] px-3">
                <span className="text-white/40">$</span>
                <input
                  type="number" min="0.01" step="any" value={budget}
                  onChange={(e) => setBudget(e.target.value)}
                  className="w-20 bg-transparent px-1 font-mono text-[14px] text-white outline-none"
                />
              </span>
            </label>
            <label className="flex h-10 cursor-pointer items-center gap-2 text-[13px] text-white/60">
              <input type="checkbox" checked={cheap} onChange={(e) => setCheap(e.target.checked)} className="accent-amber-300" />
              One cheap model for every seat
            </label>
          </div>

          {error && <p className="rounded-md border border-red-400/30 bg-red-950/40 px-3 py-2 text-[13px] text-red-200">{error}</p>}

          <button
            type="submit"
            disabled={busy || picked.length === 0 || goal.trim().length < 3 || !(Number(budget) > 0)}
            className="w-full rounded-xl bg-amber-300 py-3 text-[15px] font-medium text-black shadow-[0_0_40px_rgba(252,211,77,0.2)] transition-opacity disabled:opacity-40"
          >
            {busy ? "Convening…" : "Convene the council"}
          </button>
        </form>

        <DemoList className="mt-14" />

        {runs.length > 0 && (
          <section className="mt-14">
            <h2 className="mb-3 text-[11px] uppercase tracking-[0.2em] text-white/40">Recent runs</h2>
            <ul className="divide-y divide-white/[0.06] rounded-xl border border-white/[0.07]">
              {runs.map((r) => (
                <li key={r.id}>
                  <Link href={`/chamber/${r.id}`} className="flex items-center gap-4 px-4 py-3 hover:bg-white/[0.03]">
                    <span className="min-w-0 flex-1 truncate text-[13px] text-white/75">{r.goal}</span>
                    <span className="font-mono text-[11px] text-white/35">${r.spent_usd.toFixed(4)}</span>
                    <span className="w-16 text-right text-[11px] text-white/40">{r.status}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}
        <p className="mt-10 text-center text-[11px] text-white/25">
          <Link href="/test" className="hover:text-white/50">Single model test call</Link>
        </p>
      </div>
    </main>
  );
}
