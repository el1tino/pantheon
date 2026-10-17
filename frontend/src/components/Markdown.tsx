// A small, safe Markdown renderer for council output: headings, paragraphs, lists,
// tables, **bold**, _italic_ and `code`. Everything is rendered as React text, never HTML.

import { Fragment, type ReactNode } from "react";

function inline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|_[^_\s][^_]*_|\*[^*\s][^*]*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4)
      return <strong key={i} className="font-semibold text-white">{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2)
      return <code key={i} className="rounded bg-white/10 px-1 font-mono text-[0.9em]">{part.slice(1, -1)}</code>;
    if ((part.startsWith("_") && part.endsWith("_")) || (part.startsWith("*") && part.endsWith("*")))
      if (part.length > 2) return <em key={i} className="italic text-white/70">{part.slice(1, -1)}</em>;
    return <Fragment key={i}>{part}</Fragment>;
  });
}

const cells = (row: string) => row.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());

export default function Markdown({ text, className = "" }: { text: string; className?: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) {
      i++;
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(trimmed);
    if (heading) {
      const level = heading[1].length;
      const cls =
        level === 1 ? "text-[1.35em] font-semibold text-white mt-1"
          : level === 2 ? "text-[1.12em] font-semibold text-white mt-3"
            : "text-[1em] font-semibold text-white/90 mt-2";
      blocks.push(<div key={i} className={cls}>{inline(heading[2])}</div>);
      i++;
      continue;
    }
    if (trimmed.startsWith("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const head = cells(trimmed);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(cells(lines[i++]));
      blocks.push(
        <div key={`t${i}`} className="overflow-x-auto">
          <table className="w-full border-collapse text-[0.92em]">
            <thead>
              <tr>{head.map((h, j) => <th key={j} className="border-b border-white/15 px-2 py-1.5 text-left font-medium text-white/85">{inline(h)}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((r, k) => (
                <tr key={k}>{r.map((c, j) => <td key={j} className="border-b border-white/[0.06] px-2 py-1.5 text-white/75">{inline(c)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (/^([-*•]|\d+[.)])\s+/.test(trimmed)) {
      const ordered = /^\d/.test(trimmed);
      const items: string[] = [];
      while (i < lines.length && /^([-*•]|\d+[.)])\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^([-*•]|\d+[.)])\s+/, ""));
        i++;
      }
      const List = ordered ? "ol" : "ul";
      blocks.push(
        <List key={`l${i}`} className={`space-y-1 pl-5 ${ordered ? "list-decimal" : "list-disc"} marker:text-white/35`}>
          {items.map((it, j) => <li key={j}>{inline(it)}</li>)}
        </List>,
      );
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|[-*•]\s|\d+[.)]\s|\|)/.test(lines[i].trim())) {
      para.push(lines[i].trim());
      i++;
    }
    if (!para.length) {
      para.push(trimmed);
      i++;
    }
    blocks.push(<p key={`p${i}`}>{inline(para.join(" "))}</p>);
  }
  return <div className={`space-y-2.5 leading-relaxed ${className}`}>{blocks}</div>;
}
