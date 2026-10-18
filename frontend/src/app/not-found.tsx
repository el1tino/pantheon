import Link from "next/link";
import { APP_NAME, THE_GROUP } from "@/lib/app";

export default function NotFound() {
  return (
    <main className="chamber-stage flex min-h-dvh flex-col items-center justify-center px-4 text-center">
      <p className="text-[13px] font-semibold uppercase tracking-[0.5em] text-white/80">{APP_NAME}</p>
      <p className="mt-4 text-[15px] text-white/75">There&apos;s nothing here.</p>
      <Link href="/" className="mt-6 text-[13px] text-amber-100/80 hover:text-amber-100">
        Back to {THE_GROUP}
      </Link>
    </main>
  );
}
