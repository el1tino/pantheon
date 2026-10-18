import { APP_NAME } from "@/lib/app";

/** The app's mark: its icon and its name, set like a name rather than spaced-out capitals. */
export default function Wordmark({ size = 15, className = "" }: { size?: number; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 font-semibold tracking-tight text-white ${className}`} style={{ fontSize: size }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/icon.svg" alt="" width={size + 7} height={size + 7} className="rounded-[7px]" />
      {APP_NAME}
    </span>
  );
}
