"use client";

import { Suspense, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import AuthCard from "@/components/auth/AuthCard";
import DemoList from "@/components/DemoList";
import { login, me } from "@/lib/api";

function safeNext(next: string | null) {
  // Only same-site paths, so the login can't be used to bounce people elsewhere.
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

function Login() {
  const params = useSearchParams();
  // Already logged in: go straight on.
  useEffect(() => {
    me()
      .then(() => window.location.replace(safeNext(params.get("next"))))
      .catch(() => {});
  }, [params]);
  return (
    <AuthCard
      title="Log in"
      submitLabel="Log in"
      note="New here? You need an invite link from the owner."
      onSubmit={async (email, password) => {
        await login(email, password);
        window.location.assign(safeNext(params.get("next")));
      }}
    >
      <DemoList className="mt-14 max-w-sm" />
    </AuthCard>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <Login />
    </Suspense>
  );
}
