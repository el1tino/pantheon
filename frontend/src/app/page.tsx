import Link from "next/link";
import { APP_NAME } from "@/lib/app";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-6 text-center">
      <h1 className="text-5xl font-semibold tracking-tight">{APP_NAME}</h1>
      <p className="max-w-md text-muted">
        A council of AI models that debates your goal, splits the work and builds the result.
      </p>
      <Link
        href="/test"
        className="rounded-md border border-white/15 px-4 py-2 text-sm transition-colors hover:border-white/40"
      >
        Test a model call →
      </Link>
    </main>
  );
}
