"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import Wordmark from "@/components/Wordmark";

type Props = {
  title: string;
  submitLabel: string;
  newPassword?: boolean; // invite sign-up: ask for the password twice
  note?: React.ReactNode;
  onSubmit: (email: string, password: string) => Promise<void>;
  children?: React.ReactNode;
};

const field =
  "glass-well h-11 w-full rounded-xl px-3.5 text-[14px] text-white outline-none transition-colors placeholder:text-white/25";

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
        <div className="flex justify-center"><Wordmark /></div>
        <h1 className="mt-5 text-center text-[30px] font-semibold tracking-[-0.025em] text-white">{title}</h1>
        {note && <p className="mt-3 text-center text-[13px] text-white/45">{note}</p>}
        <form onSubmit={submit} className="glass mt-8 space-y-3 rounded-[24px] p-5">
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
          {error && <p className="rounded-xl border border-red-400/30 bg-red-950/40 px-3 py-2 text-[13px] text-red-200">{error}</p>}
          <button
            type="submit" disabled={busy}
            className="h-11 w-full accent-button rounded-full text-[14px] font-medium transition-opacity disabled:opacity-40"
          >
            {busy ? "One moment…" : submitLabel}
          </button>
        </form>
      </motion.div>
      {children}
    </main>
  );
}
