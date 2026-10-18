"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import AuthCard from "@/components/auth/AuthCard";
import { acceptInvite, checkInvite } from "@/lib/api";

export default function InvitePage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = use(params);
  const [valid, setValid] = useState<boolean | null>(null);
  useEffect(() => {
    checkInvite(code).then((r) => setValid(r.valid)).catch(() => setValid(false));
  }, [code]);

  if (valid === false) {
    return (
      <main className="chamber-stage flex min-h-dvh flex-col items-center justify-center px-4 text-center">
        <p className="text-[15px] text-white/75">This invite is used, expired or wrong.</p>
        <p className="mt-2 text-[13px] text-white/40">Ask the owner for a new link.</p>
        <Link href="/login" className="mt-6 text-[13px] text-amber-100/80 hover:text-amber-100">Log in instead</Link>
      </main>
    );
  }
  return (
    <AuthCard
      title="You're invited"
      submitLabel="Create my account"
      newPassword
      note="Pick the email and password you'll log in with."
      onSubmit={async (email, password) => {
        await acceptInvite(code, email, password);
        window.location.assign("/");
      }}
    />
  );
}
