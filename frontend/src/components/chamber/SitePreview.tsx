"use client";

import { siteUrl } from "@/lib/api";

/**
 * The council's site, live. `allow-scripts` without `allow-same-origin` gives the page an
 * opaque origin: its JavaScript runs, but it can't read the app's cookies or storage. The
 * backend's CSP stops it from making network requests, and its form-action 'none' means
 * `allow-forms` only lets the page's own submit handlers run, never send anything.
 */
export default function SitePreview({ runId, version, path = "index.html", className = "" }: {
  runId: string;
  version: number;
  path?: string;
  className?: string;
}) {
  return (
    <iframe
      key={version}
      title="Site preview"
      src={siteUrl(runId, path, version)}
      sandbox="allow-scripts allow-forms"
      referrerPolicy="no-referrer"
      className={`h-full w-full rounded-lg border border-white/10 bg-white ${className}`}
    />
  );
}
