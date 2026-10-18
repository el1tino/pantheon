"use client";

import { siteUrl } from "@/lib/api";
import { useRunInfo } from "@/lib/chamber/runInfo";

/**
 * The council's site, live. `allow-scripts` without `allow-same-origin` gives the page an
 * opaque origin: its JavaScript runs, but it can't read the app's cookies or storage. The
 * backend's CSP stops it from making network requests, and its form-action 'none' means
 * `allow-forms` only lets the page's own submit handlers run, never send anything.
 */
export default function SitePreview({ version, path = "index.html", className = "" }: {
  version: number;
  path?: string;
  className?: string;
}) {
  const { siteKey } = useRunInfo();
  return (
    <iframe
      key={version}
      title="Site preview"
      src={siteUrl(siteKey, path, version)}
      sandbox="allow-scripts allow-forms"
      referrerPolicy="no-referrer"
      className={`h-full w-full rounded-lg border border-white/10 bg-white ${className}`}
    />
  );
}
