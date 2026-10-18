"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import Markdown from "@/components/Markdown";
import { TreeFile, fileText, runTree, siteUrl } from "@/lib/api";
import { useRunInfo } from "@/lib/chamber/runInfo";
import { SeatView } from "@/lib/chamber/reducer";
import { FileView, ImageView, MODERATOR } from "@/lib/chamber/types";
import CheckReport from "./CheckReport";
import Gallery from "./Gallery";
import SitePreview from "./SitePreview";

type Props = {
  runId: string;
  files: Record<string, FileView>;
  seats: SeatView[];
  siteVersion: number;
  images: ImageView[];
  onClose: () => void;
};

const PREVIEW = "__preview__";
const GALLERY = "__gallery__";
const isImage = (p: string) => /\.(svg|png|webp|jpg)$/i.test(p);
const isCheck = (p: string) => /^logs\/check-\d+\.json$/.test(p);
const HIDDEN = new Set(["transcript.json"]);

/** Everything the run produced: the site preview, code with line numbers, and documents. */
export default function Vault({ runId, files, seats, siteVersion, images, onClose }: Props) {
  const { siteKey, replay } = useRunInfo();
  const [fullTree, setTree] = useState<TreeFile[]>([]);
  // In Replay the files on disk are the finished ones: list only those written so far.
  const tree = useMemo(() => (replay ? fullTree.filter((f) => f.path in files) : fullTree), [replay, fullTree, files]);
  const [selected, setSelected] = useState<string | null>(null);
  const [text, setText] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const changes = Object.values(files).reduce((n, f) => n + f.versions, 0);

  useEffect(() => {
    runTree(runId).then((t) => setTree(t.filter((f) => !HIDDEN.has(f.path)))).catch((e) => setError(String(e)));
  }, [runId, changes]);

  const hasSite = tree.some((f) => f.path === "site/index.html");
  const current = selected ?? (hasSite ? PREVIEW : images.length ? GALLERY
    : tree.find((f) => f.path.startsWith("docs/"))?.path ?? tree[0]?.path ?? null);
  const special = current === PREVIEW || current === GALLERY || (current !== null && isImage(current));

  const currentVersion = files[current ?? ""]?.versions ?? 0;
  useEffect(() => {
    if (!current || special) return;
    let cancelled = false;
    fileText(runId, current)
      .then((t) => !cancelled && setText(t))
      .catch((e) => !cancelled && setText(`Could not load: ${e}`));
    return () => {
      cancelled = true;
    };
  }, [runId, current, currentVersion, special]);

  const groups = useMemo(() => {
    const g = new Map<string, TreeFile[]>();
    for (const f of tree) {
      const dir = f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : "";
      g.set(dir, [...(g.get(dir) ?? []), f]);
    }
    return [...g.entries()].sort(([a], [b]) => (a === "site" ? -1 : b === "site" ? 1 : a.localeCompare(b)));
  }, [tree]);

  const colourOf = (l?: string) => (l === MODERATOR ? "#fff" : seats.find((s) => s.letter === l)?.colour ?? "#666");
  const isMd = current?.endsWith(".md");

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 20 }}
      transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      className="absolute inset-3 z-40 flex flex-col overflow-hidden glass-thick rounded-[22px]"
    >
      <div className="flex items-center gap-3 border-b border-white/[0.07] px-5 py-3">
        <span className="text-[15px] font-semibold text-white/90">Vault</span>
        <span className="text-[12px] text-white/35">{tree.length} files</span>
        {current && current !== PREVIEW && (
          <a href={`/api/runs/${runId}/files/${current}`} className="ml-4 text-[12px] text-white/50 hover:text-white">Download {current.split("/").pop()}</a>
        )}
        <button onClick={onClose} className="ml-auto text-[12px] text-white/45 hover:text-white">Close</button>
      </div>
      <div className="flex min-h-0 flex-1">
        <nav className="w-60 shrink-0 overflow-y-auto border-r border-white/[0.06] p-2 text-[12.5px]">
          {hasSite && (
            <button
              onClick={() => setSelected(PREVIEW)}
              className={`mb-2 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left ${current === PREVIEW ? "bg-amber-200/10 text-amber-100" : "text-white/70 hover:bg-white/[0.04]"}`}
            >
              <span className="text-amber-200">▶</span> Live preview
            </button>
          )}
          {images.length > 0 && (
            <button
              onClick={() => setSelected(GALLERY)}
              className={`mb-2 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left ${current === GALLERY ? "bg-amber-200/10 text-amber-100" : "text-white/70 hover:bg-white/[0.04]"}`}
            >
              <span className="text-amber-200">▦</span> Images ({images.length})
            </button>
          )}
          {groups.map(([dir, items]) => (
            <div key={dir} className="mb-2">
              <div className="px-2 py-1 text-[11.5px] text-white/30">{dir || "run"}</div>
              {items.map((f) => {
                const info = files[f.path];
                return (
                  <button
                    key={f.path}
                    onClick={() => setSelected(f.path)}
                    className={`flex w-full items-center gap-2 rounded-md px-2 py-1 text-left font-mono text-[11.5px] ${current === f.path ? "bg-white/[0.08] text-white" : "text-white/60 hover:bg-white/[0.04]"}`}
                  >
                    <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: colourOf(info?.seat) }} />
                    <span className="truncate">{f.path.split("/").pop()}</span>
                    {info && info.versions > 1 && <span className="ml-auto text-[10px] text-white/30">v{info.versions}</span>}
                  </button>
                );
              })}
            </div>
          ))}
          {error && <p className="px-2 text-[11px] text-red-300">{error}</p>}
        </nav>
        <div className="min-w-0 flex-1 overflow-auto p-4">
          {!current && <p className="text-[13px] text-white/35">Nothing has been written yet.</p>}
          {current === PREVIEW && <SitePreview version={siteVersion} />}
          {current === GALLERY && <Gallery images={images} seats={seats} version={siteVersion} />}
          {current && !special && isCheck(current) && <CheckReport text={text} onOpenFile={(p) => setSelected(p)} />}
          {current && current !== GALLERY && isImage(current) && (
            <div className="checkerboard flex h-full items-center justify-center rounded-lg p-6">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={siteUrl(siteKey, current.replace(/^site\//, ""), siteVersion)} alt={current} className="max-h-full max-w-full" />
            </div>
          )}
          {current && !special && !isCheck(current) && isMd && (
            <div className="mx-auto max-w-3xl text-[14px] text-white/80"><Markdown text={text} /></div>
          )}
          {current && !special && !isCheck(current) && !isMd && (
            <pre className="font-mono text-[12px] leading-[1.6] text-white/80">
              {text.split("\n").map((line, i) => (
                <div key={i} className="flex">
                  <span className="mr-4 w-8 shrink-0 select-none text-right text-white/25">{i + 1}</span>
                  <span className="whitespace-pre-wrap break-all">{line || " "}</span>
                </div>
              ))}
            </pre>
          )}
        </div>
      </div>
    </motion.div>
  );
}
