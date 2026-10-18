"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { APP_NAME } from "@/lib/app";

type Props = {
  title: string;
  submitLabel: string;
  newPassword?: boolean; // invite sign-up: ask for the password twice
  note?: React.ReactNode;
  onSubmit: (email: string, password: string) => Promise<void>;
  children?: React.ReactNode;
};

const field =
  "h-11 w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 text-[14px] text-white outline-none transition-colors placeholder:text-white/25 focus:border-white/30";

/** The email-and-password card used by the login and the invite pages. */
export default function AuthCard({ title, submitLabel, newPassword = false, note, onSubmit, children }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword && password !== again) return setError("The two passwords don't match.");
    setBusy(true);
    setError(null);
    try {
      await onSubmit(email.trim(), password);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  return (
    <main className="chamber-stage flex min-h-dvh flex-col items-center px-4 py-16 md:py-24">
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }} className="w-full max-w-sm">
        <p className="text-center text-[13px] font-semibold uppercase tracking-[0.5em] text-white/80">{APP_NAME}</p>
        <h1 className="mt-3 text-center text-2xl font-medium tracking-tight text-white">{title}</h1>
        {note && <p className="mt-3 text-center text-[13px] text-white/45">{note}</p>}
        <form onSubmit={submit} className="mt-8 space-y-3">
          <input
            type="email" required autoComplete="email" placeholder="Email" value={email}
            onChange={(e) => setEmail(e.target.value)} className={field}
          />
          <input
            type="password" required autoComplete={newPassword ? "new-password" : "current-password"}
            minLength={newPassword ? 10 : undefined} placeholder={newPassword ? "Password (10+ characters)" : "Password"}
            value={password} onChange={(e) => setPassword(e.target.value)} className={field}
          />
          {newPassword && (
            <input
              type="password" required autoComplete="new-password" placeholder="Password again" value={again}
              onChange={(e) => setAgain(e.target.value)} className={field}
            />
          )}
          {error && <p className="rounded-md border border-red-400/30 bg-red-950/40 px-3 py-2 text-[13px] text-red-200">{error}</p>}
          <button
            type="submit" disabled={busy}
            className="h-11 w-full rounded-lg bg-amber-300 text-[14px] font-medium text-black shadow-[0_0_40px_rgba(252,211,77,0.2)] transition-opacity disabled:opacity-40"
          >
            {busy ? "One moment…" : submitLabel}
          </button>
        </form>
      </motion.div>
      {children}
    </main>
  );
}
