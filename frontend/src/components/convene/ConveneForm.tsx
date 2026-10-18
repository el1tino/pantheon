"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { CAP_A_GROUP, GROUP_NAME, THE_GROUP } from "@/lib/app";
import DemoList from "@/components/DemoList";
import Wordmark from "@/components/Wordmark";
import SeatLogo from "@/components/SeatLogo";
import TrademarkNote from "@/components/TrademarkNote";
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
    <div className="flex flex-col items-end gap-2 text-[13px] text-white/50">
      <div className="flex items-center gap-4 whitespace-nowrap">
        <span className="hidden max-w-[220px] truncate sm:inline">{user.email}</span>
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
        <div className="flex w-full max-w-md items-center gap-2 glass-chip rounded-xl !border-amber-200/20 p-2">
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
        <div className="flex justify-center"><Wordmark /></div>
        <p className="mt-3 text-center text-2xl font-medium tracking-tight text-white">{CAP_A_GROUP} of AI models, at work</p>
        <p className="mt-3 text-center text-[13px] leading-relaxed text-white/45">
          Models from different providers debate a goal, vote on who does what and build the result. This is a
          recorded run made with the built-in practice {GROUP_NAME}, so its replies are scripted. New runs are
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
        <Wordmark />
        <p className="mt-4 text-[15px] text-white/75">Can&apos;t reach {THE_GROUP}.</p>
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
    <main className="chamber-stage min-h-dvh px-5 py-8 md:py-10">
      <div className="mx-auto max-w-3xl">
        <header className="flex items-start justify-between gap-6">
          <Wordmark />
          <AccountBar user={user} />
        </header>
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}>
          <h1 className="mt-14 max-w-xl text-[34px] font-semibold leading-[1.08] tracking-[-0.025em] text-white md:text-[44px]">
            What should {THE_GROUP} work on?
          </h1>
          <p className="mt-4 max-w-lg text-[16px] leading-relaxed text-white/55">
            Ask it the way you&apos;d ask a person. The models debate it, vote on who does what and deliver the
            result while you watch.
          </p>
        </motion.div>

        <form onSubmit={submit} className="glass mt-8 space-y-8 rounded-[28px] p-5 md:p-7">
          <label className="block">
            <span className="sr-only">Your goal</span>
            <textarea
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder={EXAMPLES[mission] ?? EXAMPLES.auto}
              rows={3}
              autoFocus
              className="w-full resize-y glass-well rounded-2xl p-4 text-[17px] leading-relaxed text-white outline-none transition-colors placeholder:text-white/25"
            />
          </label>
          <div>
            <span className="mb-2.5 block text-[13px] font-medium text-white/60">Kind of job</span>
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
                    {!m.available && <span className="ml-1.5 text-[11px] text-white/30">soon</span>}
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


          <div>
            <div className="mb-3 flex items-baseline justify-between">
              <span className="text-[13px] font-medium text-white/60">Who attends</span>
              <span className="text-[13px] text-white/40">{picked.length} of {seats.length || 13} seats</span>
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
                    className={`group flex items-center gap-3 rounded-2xl border px-3 py-2.5 text-left transition-all duration-300 ${on ? "glass" : "border-white/[0.06]"}`}
                    style={on ? { borderColor: `${s.colour}55`, boxShadow: `inset 0 1px 0 rgba(255,255,255,0.08), 0 0 24px -6px ${s.colour}55` } : undefined}
                  >
                    <span
                      className="seat-disc relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-opacity"
                      style={{ opacity: on ? 1 : 0.45, borderColor: on ? `${s.colour}55` : undefined }}
                    >
                      <SeatLogo seat={s} size={18} />
                      <span className="absolute -bottom-1 -right-1 text-[9px] font-medium" style={{ color: s.colour }}>
                        {s.letter}
                      </span>
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
              <span className="mb-2.5 block text-[13px] font-medium text-white/60">Debate rounds</span>
              <select
                value={rounds}
                onChange={(e) => setRounds(Number(e.target.value))}
                className="h-10 rounded-xl border border-white/10 bg-[#17181e] px-3 text-[14px] text-white outline-none"
              >
                {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="mb-2.5 block text-[13px] font-medium text-white/60">Spend at most</span>
              <span className="glass-well flex h-10 items-center rounded-xl px-3">
                <span className="text-white/40">$</span>
                <input
                  type="number" min="0.01" step="any" value={budget}
                  onChange={(e) => setBudget(e.target.value)}
                  className="w-20 bg-transparent px-1 text-[14px] text-white outline-none"
                />
              </span>
            </label>
            <label className="flex h-10 cursor-pointer items-center gap-2 text-[13px] text-white/60">
              <input type="checkbox" checked={cheap} onChange={(e) => setCheap(e.target.checked)} className="accent-amber-300" />
              One cheap model for every seat
            </label>
          </div>

          {error && <p className="rounded-xl border border-red-400/30 bg-red-950/40 px-3 py-2 text-[13px] text-red-200">{error}</p>}

          <button
            type="submit"
            disabled={busy || picked.length === 0 || goal.trim().length < 3 || !(Number(budget) > 0)}
            className="w-full accent-button rounded-full py-3 text-[15px] font-medium transition-opacity disabled:opacity-40"
          >
            {busy ? "Convening…" : `Convene ${THE_GROUP}`}
          </button>
        </form>

        <DemoList className="mt-14" />

        {runs.length > 0 && (
          <section className="mt-14">
            <h2 className="mb-3 text-[15px] font-semibold text-white/85">Your runs</h2>
            <ul className="glass divide-y divide-white/[0.06] overflow-hidden rounded-2xl">
              {runs.map((r) => (
                <li key={r.id}>
                  <Link href={`/chamber/${r.id}`} className="flex items-center gap-4 px-4 py-3 hover:bg-white/[0.03]">
                    <span className="min-w-0 flex-1 truncate text-[14px] text-white/80">{r.goal}</span>
                    <span className="text-[12px] text-white/40">${r.spent_usd.toFixed(4)}</span>
                    <span className="w-16 text-right text-[12px] text-white/45">{r.status}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}
        <p className="mt-10 text-center text-[11px] text-white/25">
          <Link href="/test" className="hover:text-white/50">Single model test call</Link>
        </p>
        <TrademarkNote className="mt-3" />
      </div>
    </main>
  );
}
