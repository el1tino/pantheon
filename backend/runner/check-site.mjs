// Checks a static site mounted read-only at /work/site and prints one JSON report.
// Runs inside a locked-down container: no network, read-only filesystem, no secrets.
//
//   - every local href/src in every HTML page resolves to a file
//   - every .js file parses (node --check equivalent via vm.Script)
//   - each page loads in jsdom with its scripts running; script errors and console.error
//     calls are collected
//   - whether a logo image (path containing "logo") is referenced and exists

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { JSDOM, VirtualConsole, ResourceLoader } from "jsdom";

const ROOT = process.argv[2] || "/work/site";
const report = { ok: true, pages: [], errors: [], warnings: [], logo: null, files: [] };

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((d) => {
    const p = path.join(dir, d.name);
    return d.isDirectory() ? walk(p) : [p];
  });
}

function rel(p) {
  return path.relative(ROOT, p).split(path.sep).join("/");
}

function fail(file, kind, message, line) {
  report.ok = false;
  report.errors.push({ file: file ? `site/${file}` : null, kind, message: String(message).slice(0, 500), line: line ?? null });
}

if (!fs.existsSync(path.join(ROOT, "index.html"))) {
  fail("index.html", "missing", "site/index.html does not exist");
}

const files = fs.existsSync(ROOT) ? walk(ROOT) : [];
report.files = files.map(rel);

// 1. JavaScript syntax
for (const f of files.filter((f) => f.endsWith(".js"))) {
  try {
    new vm.Script(fs.readFileSync(f, "utf8"), { filename: rel(f) });
  } catch (e) {
    const line = /:(\d+)/.exec(String(e.stack))?.[1];
    fail(rel(f), "syntax", e.message, line ? Number(line) : null);
  }
}

// Only files inside the site may be loaded; nothing from the network.
class LocalOnly extends ResourceLoader {
  fetch(url, options) {
    if (!url.startsWith("file://")) return null;
    const p = decodeURIComponent(new URL(url).pathname);
    if (!p.startsWith(ROOT)) return null;
    return super.fetch(url, options);
  }
}

// 2 + 3. Links and runtime, page by page
for (const page of files.filter((f) => f.endsWith(".html"))) {
  const name = rel(page);
  const html = fs.readFileSync(page, "utf8");
  const refs = [...html.matchAll(/\b(?:src|href)\s*=\s*["']([^"'#?]+)/gi)].map((m) => m[1]);
  const pageInfo = { page: `site/${name}`, refs: [], scriptErrors: 0, consoleErrors: 0 };
  for (const ref of refs) {
    if (/^(https?:|mailto:|tel:|data:|javascript:|\/\/)/i.test(ref)) {
      report.warnings.push({ file: `site/${name}`, message: `external reference not checked: ${ref}` });
      continue;
    }
    const target = path.resolve(path.dirname(page), ref.startsWith("/") ? path.join(ROOT, ref) : ref);
    const exists = target.startsWith(ROOT) && fs.existsSync(target) && fs.statSync(target).isFile();
    pageInfo.refs.push({ ref, exists });
    if (!exists) fail(name, "missing", `${ref} is referenced but does not exist`);
    if (/logo/i.test(ref)) report.logo = { ref, exists, page: `site/${name}` };
  }

  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (e) => {
    if (/ENOENT/.test(String(e.detail?.message || e.message))) return; // the link check reports it
    pageInfo.scriptErrors += 1;
    const where = /at (?:.*?\()?file:\/\/[^)]*?\/site\/([^:)]+):(\d+)/.exec(String(e.detail?.stack || e.stack || ""));
    fail(where ? where[1] : name, "runtime", e.detail?.message || e.message, where ? Number(where[2]) : null);
  });
  virtualConsole.on("error", (...args) => {
    pageInfo.consoleErrors += 1;
    fail(name, "console", args.map(String).join(" "));
  });
  try {
    const dom = new JSDOM(html, {
      url: `file://${page}`,
      runScripts: "dangerously",
      resources: new LocalOnly(),
      pretendToBeVisual: true,
      virtualConsole,
    });
    dom.window.IntersectionObserver ??= class { observe() {} unobserve() {} disconnect() {} };
    await new Promise((resolve) => {
      dom.window.addEventListener("load", resolve);
      setTimeout(resolve, 4000);
    });
    await new Promise((r) => setTimeout(r, 300));
    pageInfo.title = dom.window.document.title;
    dom.window.close();
  } catch (e) {
    fail(name, "load", e.message);
  }
  report.pages.push(pageInfo);
}

if (!report.logo) report.warnings.push({ file: "site/index.html", message: "no logo image is referenced" });
console.log(JSON.stringify(report));
