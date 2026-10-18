"""The Integrate phase for Build and Launch: run the site in Docker, send errors back to the
owners, make sure the site uses its own logo, and a consistency pass over name, colours and
prices across the site and the documents.
"""

import json
from collections import defaultdict
from typing import Any

from app.orchestrator import sandbox
from app.orchestrator.building import BuildTask
from app.orchestrator.debate import MODERATOR
from app.orchestrator.execution import CheckResult, check_site

MAX_FIX_LOOPS = 2
MAX_CONSISTENCY_ISSUES = 6
CONSISTENCY_CHARS = 30_000


class IntegrateMixin:
    """Mixed into MissionRun after BuildMixin."""

    def _init_integrate(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.check_status: str | None = None

    # ------------------------------------------------------------ checks + error loop

    async def _step_integrate(self, step) -> None:
        if not self.build_tasks:
            return
        await self._ensure_logo()
        for loop in range(MAX_FIX_LOOPS + 1):
            result = await self._run_check()
            if result.status != "failed" or loop == MAX_FIX_LOOPS:
                break
            await self._send_errors_back(result)

    async def _run_check(self) -> CheckResult:
        await self._gate()
        self.log.emit("phase_changed", phase=self.phase, round="check")
        self.log.emit("seat_thinking", seat=MODERATOR, state="thinking", activity="running the site in Docker")
        result = await check_site(sandbox.run_dir(self.run_id) / "site")
        result = self._require_logo(result)
        n = len(self.checks) + 1
        path = f"logs/check-{n}.json"
        log = {"check": n, **result.as_dict()}
        self._write_file(MODERATOR, path, json.dumps(log, indent=2) + "\n")
        self.checks.append({"path": path, **log})
        self.check_status = result.status
        self.log.emit("artifact_created", path=path, kind="check", status=result.status,
                      errors=len(result.errors), warnings=len(result.warnings), detail=result.detail)
        if result.status == "passed":
            note = f"Check {n} passed in Docker: the site loads, its scripts run and every file it uses exists."
        elif result.status == "not_run":
            note = f"Check {n} was not run: {result.detail} Claims that the site works stay unverified."
        else:
            first = "; ".join(f"{e.get('file') or 'site'}: {e['message']}" for e in result.errors[:3])
            note = f"Check {n} failed with {len(result.errors)} error(s): {first}"
        self._moderator_note("check", note)
        return result

    def _require_logo(self, result: CheckResult) -> CheckResult:
        """Done means the site uses its own generated logo."""
        logos = [i["path"] for i in self.images if i["kind"] == "logo"]
        if result.status == "not_run" or not logos:
            return result
        used = result.logo and result.logo.get("exists")
        if not used:
            result.errors.append({"file": "site/index.html", "kind": "logo", "line": None,
                                  "message": f"The page does not use the generated logo ({logos[-1]}). "
                                             "Show it in the header with an <img> tag."})
            result.status = "failed"
        return result

    def _owner_task(self, path: str | None) -> BuildTask | None:
        tid = self.file_owner.get(path or "") or self.file_owner.get("site/index.html")
        return next((t for t in self.build_tasks if t.id == tid), None)

    async def _send_errors_back(self, result: CheckResult) -> None:
        by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for err in result.errors:
            task = self._owner_task(err.get("file"))
            if task:
                by_task[task.id].append(err)
        log_path = self.checks[-1]["path"]
        self.log.emit("phase_changed", phase=self.phase, round="fix")
        for t in self.build_tasks:
            errs = by_task.get(t.id)
            if not errs or not self._ensure_people(t):
                continue
            lines = "\n".join(
                f"- {e.get('file') or 'site'}" + (f" line {e['line']}" if e.get("line") else "")
                + f" [{e.get('kind')}]: {e['message']}" for e in errs
            )
            self._task_status(t, "changes", check=log_path)
            revised = await self._build_turn(
                t, "revise", feedback=f"The site was run in Docker and failed ({log_path}):\n{lines}\n"
                                      "Fix these errors in your files.")
            if revised:
                await self._save_work(t, *revised)
            self._task_status(t, "done")

    async def _ensure_logo(self) -> None:
        """If nobody commissioned a logo yet, the owner of the page gets one made and placed."""
        if any(i["kind"] == "logo" for i in self.images):
            return
        task = self._owner_task("site/index.html")
        if not task or not self._ensure_people(task):
            return
        self._moderator_note("check", f"The site has no logo yet, so {task.owner} gets one made for the header.")
        self._task_status(task, "changes")
        revised = await self._build_turn(
            task, "revise",
            feedback='The site needs its own logo. Request one in "proposal": {"images": [{"path": '
                     '"site/logo.svg", "kind": "logo", "prompt": "..."}]} and show it in the page header with '
                     'an <img src="logo.svg" alt="..."> tag.')
        if revised:
            await self._save_work(task, *revised)
        self._task_status(task, "done")

    # ------------------------------------------------------------ consistency pass

    async def _step_consistency(self, step) -> None:
        if not self.build_tasks:
            return
        paths = [p for p in sorted(self._written) if p.endswith((".html", ".css", ".md", ".js"))]
        context = self._file_context(paths)
        if len(context) > CONSISTENCY_CHARS:
            context = context[:CONSISTENCY_CHARS] + "\n... (truncated)"
        data = await self._moderator_json(
            "STEP: CONSISTENCY",
            "Check that the business or product name, the colours and the prices match everywhere across "
            f"these files. List at most {MAX_CONSISTENCY_ISSUES} real mismatches. Reply with only JSON: "
            '{"issues": [{"file": "<path>", "problem": "...", "fix": "..."}]} (an empty list if all match).',
            f"{self._direction()}\n\nFILES:\n{context}",
        )
        issues = [i for i in (data or {}).get("issues") or [] if isinstance(i, dict) and i.get("file")]
        issues = issues[:MAX_CONSISTENCY_ISSUES]
        if not issues:
            self._moderator_note("consistency", "Consistency pass: the name, colours and prices match everywhere.")
            return
        by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for issue in issues:
            task = self._owner_task(str(issue["file"]))
            if task:
                by_task[task.id].append(issue)
        self._moderator_note("consistency", f"Consistency pass found {len(issues)} mismatch(es): " + "; ".join(
            f"{i['file']}: {i.get('problem', '')}" for i in issues))
        self.log.emit("phase_changed", phase=self.phase, round="consistency")
        touched_site = False
        for t in self.build_tasks:
            found = by_task.get(t.id)
            if not found or not self._ensure_people(t):
                continue
            notes = "\n".join(f"- {i['file']}: {i.get('problem', '')} Fix: {i.get('fix', '')}" for i in found)
            self._task_status(t, "changes")
            revised = await self._build_turn(t, "revise", feedback=f"Consistency pass:\n{notes}")
            if revised:
                await self._save_work(t, *revised)
                touched_site = touched_site or any(f.path.startswith("site/") for f in revised[1])
            self._task_status(t, "done")
        if touched_site:
            await self._run_check()  # the fixes touched the site: run it once more
