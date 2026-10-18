"use client";

type Report = {
  check?: number;
  status: string;
  errors: { file: string | null; kind: string; message: string; line: number | null }[];
  warnings: { file: string | null; message: string }[];
  logo: { ref: string; exists: boolean } | null;
  detail?: string;
};

const BADGE: Record<string, string> = {
  passed: "border-emerald-400/40 text-emerald-300 bg-emerald-400/10",
  failed: "border-red-400/40 text-red-300 bg-red-400/10",
  not_run: "border-amber-300/40 text-amber-200 bg-amber-300/10",
};

/** A Docker check log, readable: pass/fail, each error with its file and line. */
export default function CheckReport({ text, onOpenFile }: { text: string; onOpenFile: (path: string) => void }) {
  let report: Report;
  try {
    report = JSON.parse(text);
  } catch {
    return <pre className="font-mono text-[12px] text-white/70">{text}</pre>;
  }
  return (
    <div className="mx-auto max-w-3xl space-y-4 text-[13px]">
      <div className="flex items-center gap-3">
        <span className={`rounded-full border px-3 py-1 text-[12px] font-medium uppercase tracking-wider ${BADGE[report.status] ?? ""}`}>
          {report.status.replace("_", " ")}
        </span>
        <span className="text-white/50">
          Check {report.check} · run in Docker with no network, a read-only filesystem and no secrets
        </span>
      </div>
      {report.detail && <p className="text-amber-200/80">{report.detail}</p>}
      {report.logo && (
        <p className="text-white/60">
          Logo: <span className="font-mono">{report.logo.ref}</span> {report.logo.exists ? "is used on the page ✓" : "is referenced but missing"}
        </p>
      )}
      {report.errors.length > 0 && (
        <div>
          <div className="mb-2 text-[11px] uppercase tracking-[0.2em] text-red-300/70">Errors · {report.errors.length}</div>
          <ul className="space-y-2">
            {report.errors.map((e, i) => (
              <li key={i} className="rounded-lg border border-red-400/20 bg-red-500/[0.06] p-3">
                <div className="flex flex-wrap items-center gap-2 text-[11.5px]">
                  <span className="rounded bg-red-400/15 px-1.5 uppercase tracking-wider text-red-200">{e.kind}</span>
                  {e.file && (
                    <button onClick={() => onOpenFile(e.file!)} className="font-mono text-white/70 underline decoration-white/20 hover:text-white">
                      {e.file}{e.line ? `:${e.line}` : ""}
                    </button>
                  )}
                </div>
                <p className="mt-1 font-mono text-[12px] text-red-100/80">{e.message}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
      {report.status === "passed" && <p className="text-emerald-300/80">No errors: the page loaded, its scripts ran and every file it uses exists.</p>}
      {report.warnings.length > 0 && (
        <div>
          <div className="mb-2 text-[11px] uppercase tracking-[0.2em] text-white/40">Warnings · {report.warnings.length}</div>
          <ul className="space-y-1 text-white/55">
            {report.warnings.map((w, i) => <li key={i}>{w.file ? `${w.file}: ` : ""}{w.message}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}
