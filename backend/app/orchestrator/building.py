"""Roles and building: workstreams, the task plan, and builders writing real files.

Used by MissionRun (missions.py) for the Build and Launch missions:

  workstreams  the moderator proposes workstreams; seats pitch for them and the others vote
               (no self-votes, ties to the moderator); the moderator turns the result into a
               task plan (owner, a different reviewer, files, dependencies) and the client
               approves it, swapping any assignment, at the plan checkpoint
  build        tasks run in waves that respect their dependencies, up to 3 in parallel; each
               owner writes its files, may ask a teammate one question through the board, and
               its reviewer approves or asks for specific changes (at most 2 review rounds)
"""

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.db import Task
from app.orchestrator import sandbox
from app.orchestrator.debate import MODERATOR, Entry, RunStopped
from app.orchestrator.files import FORMAT_HELP, FileBlock, clean_path, parse_build_reply
from app.orchestrator.protocol import AgentReply, ReplyError, Stance
from app.orchestrator.seats import SeatConfig

MAX_PARALLEL = 3
MAX_REVIEW_ROUNDS = 2
MAX_TASKS = 8
CONTEXT_FILE_CHARS = 12_000
CONTEXT_TOTAL_CHARS = 40_000

DEFAULT_WORKSTREAMS = {
    "build": [
        ("Copy", "The words on the site: headline, sections and calls to action."),
        ("Page structure", "The HTML: sections, navigation and content in place."),
        ("Styling", "The CSS: layout, colour, type and responsive behaviour."),
        ("Interactivity", "The JavaScript: anything that moves or responds to the visitor."),
    ],
    "launch": [
        ("Website", "The landing page: index.html, styles.css and script.js."),
        ("Copy and launch plan", "Marketing copy and a launch plan."),
        ("Business plan and pitch", "The business plan and the pitch deck text."),
    ],
}


@dataclass
class Workstream:
    id: str
    title: str
    brief: str
    lead: str | None = None
    votes: int = 0


@dataclass
class BuildTask:
    id: str
    title: str
    workstream: str
    brief: str
    files: list[str]
    depends_on: list[str] = field(default_factory=list)
    owner: str | None = None
    reviewer: str | None = None
    status: str = "planned"
    db_id: str | None = None
    entry_id: str | None = None  # the latest build message for this task
    asked: bool = False
    question: dict[str, str] | None = None
    review_rounds: int = 0

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "workstream": self.workstream, "brief": self.brief,
                "files": self.files, "depends_on": self.depends_on, "owner": self.owner,
                "reviewer": self.reviewer}


class BuildMixin:
    """Mixed into MissionRun. Relies on its helpers (_ask, _elect, _moderator_json, ...)."""

    workstreams: list[Workstream]
    build_tasks: list[BuildTask]

    def _init_build(self) -> None:
        self.workstreams = []
        self.build_tasks = []
        self.file_owner: dict[str, str] = {}  # path -> task id
        self._written: set[str] = set()

    # ------------------------------------------------------------ roles: workstreams and plan

    async def _step_workstreams(self, step) -> None:
        present = self._present()
        k = max(2, min(5, len(present)))
        data = await self._moderator_json(
            "STEP: WORKSTREAMS",
            f"{step.brief} Propose 2 to {k} workstreams that different members can lead. Reply with "
            'only JSON: {"workstreams": [{"title": "...", "brief": "one sentence"}]}',
            self._direction() or "(no direction chosen yet)",
        )
        raw = [w for w in (data or {}).get("workstreams") or [] if isinstance(w, dict) and w.get("title")]
        pairs = [(str(w["title"]).strip(), str(w.get("brief", "")).strip()) for w in raw[:k]]
        if len(pairs) < 2:
            key = self.mission.key if self.mission else "build"
            pairs = DEFAULT_WORKSTREAMS.get(key, DEFAULT_WORKSTREAMS["build"])
        self.workstreams = [Workstream(f"w{i + 1}", t, b) for i, (t, b) in enumerate(pairs)]
        self._moderator_note("workstreams", "Workstreams: " + "; ".join(
            f"{w.id} {w.title}" for w in self.workstreams) + ".")

        result = await self._elect([(w.id, w.title, w.brief) for w in self.workstreams],
                                   what="workstreams to lead", moderator_tiebreak=True)
        for w in self.workstreams:
            w.lead, w.votes = result[w.id]
            self.log.emit("task_updated", kind="workstream", task_id=None, part=w.id, title=w.title,
                          owner_seat=w.lead, status="lead", votes=w.votes)
        self._moderator_note("roles", "Leads by vote: " + "; ".join(
            f"{w.title} → {w.lead}" + (f" ({w.votes} vote{'s' if w.votes != 1 else ''})" if w.votes else "")
            for w in self.workstreams) + ".")

        self.build_tasks = await self._plan_tasks(step)
        self._assign_reviewers()
        answer = await self._checkpoint(
            "plan",
            workstreams=[{"id": w.id, "title": w.title, "brief": w.brief, "lead": w.lead, "votes": w.votes}
                         for w in self.workstreams],
            tasks=[t.public() for t in self.build_tasks],
            seats=[s.letter for s in self._present()],
        )
        self._apply_assignments(answer.get("assignments") or {})
        for t in self.build_tasks:
            row = Task(run_id=self.run_id, title=t.title, owner_seat=t.owner, reviewer_seat=t.reviewer,
                       status="planned", depends_on=",".join(t.depends_on))
            self.session.add(row)
            self.session.commit()
            t.db_id = row.id
            self._task_status(t, "planned")
        plan_md = ["# Task plan", ""] + [
            f"- **{t.id} {t.title}** ({self._ws_title(t.workstream)}): {t.owner} builds, {t.reviewer} reviews. "
            f"Files: {', '.join(t.files)}" + (f". After: {', '.join(t.depends_on)}" if t.depends_on else "")
            for t in self.build_tasks
        ]
        self._write_file(MODERATOR, "docs/plan.md", "\n".join(plan_md) + "\n")
        self._moderator_note("plan", "Plan approved: " + "; ".join(
            f"{t.id} {t.title} → {t.owner} (review {t.reviewer})" for t in self.build_tasks) + ".")

    def _ws_title(self, ws_id: str) -> str:
        return next((w.title for w in self.workstreams if w.id == ws_id), ws_id)

    async def _plan_tasks(self, step) -> list[BuildTask]:
        ws = "\n".join(f"- {w.id}: {w.title} (lead {w.lead}). {w.brief}" for w in self.workstreams)
        data = await self._moderator_json(
            "STEP: PLAN",
            f"Turn the workstreams into a task plan of at most {MAX_TASKS} tasks.\nWORKSTREAMS:\n{ws}\n"
            "Website files go under site/ (site/index.html must exist and link styles.css and script.js "
            "with relative paths). Documents go under docs/ as Markdown. Each file belongs to exactly one "
            f"task. {step.brief} Reply with only JSON: "
            '{"tasks": [{"id": "t1", "title": "...", "workstream": "w1", "brief": "...", '
            '"files": ["site/index.html"], "depends_on": ["t0"]}]}',
            self._direction() or "",
        )
        tasks = self._parse_plan((data or {}).get("tasks"))
        needs_site = self.mission is not None and self.mission.key in ("build", "launch")
        if not tasks or (needs_site and not any("site/index.html" in t.files for t in tasks)):
            tasks = self._fallback_plan()
        lead = {w.id: w.lead for w in self.workstreams}
        for t in tasks:
            t.owner = lead.get(t.workstream) or self.workstreams[0].lead
        return tasks

    def _parse_plan(self, raw: Any) -> list[BuildTask]:
        if not isinstance(raw, list):
            return []
        ws_ids = [w.id for w in self.workstreams]
        tasks: list[BuildTask] = []
        owned: set[str] = set()
        for i, item in enumerate(raw[:MAX_TASKS]):
            if not isinstance(item, dict):
                continue
            files = []
            for f in item.get("files") or []:
                try:
                    path = clean_path(str(f))
                except ReplyError:
                    continue
                if path not in owned:
                    owned.add(path)
                    files.append(path)
            if not files:
                continue
            ws = str(item.get("workstream", ""))
            tasks.append(BuildTask(
                id=f"t{len(tasks) + 1}", title=str(item.get("title") or f"Task {i + 1}").strip(),
                workstream=ws if ws in ws_ids else ws_ids[min(i, len(ws_ids) - 1)],
                brief=str(item.get("brief", "")).strip(), files=files,
                depends_on=[str(d) for d in item.get("depends_on") or []],
            ))
        # Map the moderator's ids onto ours (it may have numbered differently) and drop bad edges.
        original = [str(item.get("id", "")) for item in raw[:MAX_TASKS] if isinstance(item, dict)]
        rename = {old: t.id for old, t in zip(original, tasks, strict=False) if old}
        for t in tasks:
            t.depends_on = [rename.get(d, d) for d in t.depends_on]
            t.depends_on = [d for d in dict.fromkeys(t.depends_on) if d != t.id and d in {x.id for x in tasks}]
        return tasks if not _has_cycle(tasks) else [
            BuildTask(t.id, t.title, t.workstream, t.brief, t.files) for t in tasks
        ]

    def _fallback_plan(self) -> list[BuildTask]:
        ws = [w.id for w in self.workstreams]
        pick = lambda i: ws[min(i, len(ws) - 1)]
        if self.mission is not None and self.mission.key == "launch":
            return [
                BuildTask("t1", "Landing page", pick(0), "The landing page for the business.",
                          ["site/index.html", "site/styles.css", "site/script.js"]),
                BuildTask("t2", "Marketing copy and launch plan", pick(1),
                          "Positioning, taglines, launch posts and a 30-day launch plan.",
                          ["docs/marketing-copy.md", "docs/launch-plan.md"]),
                BuildTask("t3", "Business plan and pitch", pick(2),
                          "A lean business plan and the text of a 10-slide pitch deck.",
                          ["docs/business-plan.md", "docs/pitch-deck.md"]),
            ]
        return [
            BuildTask("t1", "Copy", pick(0), "Headline, sections, calls to action.", ["docs/copy.md"]),
            BuildTask("t2", "Page structure", pick(1), "The HTML page using the copy.", ["site/index.html"], ["t1"]),
            BuildTask("t3", "Styling", pick(2), "The stylesheet.", ["site/styles.css"], ["t2"]),
            BuildTask("t4", "Interactivity", pick(3), "The script.", ["site/script.js"], ["t2"]),
        ]

    def _assign_reviewers(self) -> None:
        load: Counter[str] = Counter()
        present = [s.letter for s in self._present()]
        for t in self.build_tasks:
            candidates = [c for c in present if c != t.owner]
            if not candidates:
                t.reviewer = None
                continue
            leads = {w.lead for w in self.workstreams}
            t.reviewer = min(candidates, key=lambda c: (load[c], c not in leads, present.index(c)))
            load[t.reviewer] += 1

    def _apply_assignments(self, assignments: dict[str, Any]) -> None:
        present = {s.letter for s in self._present()}
        for t in self.build_tasks:
            change = assignments.get(t.id)
            if not isinstance(change, dict):
                continue
            owner = str(change.get("owner") or t.owner or "").upper()
            reviewer = str(change.get("reviewer") or t.reviewer or "").upper()
            if owner in present and reviewer in present and owner != reviewer:
                t.owner, t.reviewer = owner, reviewer

    # ------------------------------------------------------------ build

    def _task_status(self, t: BuildTask, status: str, **extra: Any) -> None:
        t.status = status
        if t.db_id:
            row = self.session.get(Task, t.db_id)
            if row:
                row.status, row.owner_seat, row.reviewer_seat = status, t.owner, t.reviewer
                self.session.add(row)
                self.session.commit()
        self.log.emit("task_updated", kind="task", task_id=t.db_id, part=t.id, title=t.title,
                      owner_seat=t.owner, reviewer_seat=t.reviewer, status=status, files=t.files,
                      depends_on=t.depends_on, workstream=self._ws_title(t.workstream),
                      question=t.question, **extra)

    async def _step_build(self, step) -> None:
        remaining = list(self.build_tasks)
        done: set[str] = set()
        ids = {t.id for t in remaining}
        while remaining:
            if not self._present():
                raise RunStopped("Every seat is absent, so the build cannot continue.")
            wave = [t for t in remaining if all(d in done or d not in ids for d in t.depends_on)] or remaining
            self.log.emit("phase_changed", phase=self.phase, round="build")
            gate = asyncio.Semaphore(MAX_PARALLEL)

            async def run(task: BuildTask, gate: asyncio.Semaphore = gate) -> None:
                async with gate:
                    await self._run_task(task)

            jobs = [asyncio.create_task(run(t)) for t in wave]
            try:
                await asyncio.gather(*jobs)
            except BaseException:
                for j in jobs:
                    j.cancel()
                raise
            for t in wave:
                done.add(t.id)
                remaining.remove(t)

    def _ensure_people(self, t: BuildTask) -> bool:
        """Reassign a task whose owner or reviewer is absent. False if nobody can build it."""
        present = [s.letter for s in self._present()]
        if not present:
            return False
        load = Counter(x.owner for x in self.build_tasks if x.status != "done")
        if t.owner not in present:
            choices = [c for c in present if c != t.reviewer] or present
            t.owner = min(choices, key=lambda c: (load[c], present.index(c)))
            self._task_status(t, t.status, reassigned=True)
        if t.reviewer not in present or t.reviewer == t.owner:
            others = [c for c in present if c != t.owner]
            t.reviewer = others[0] if others else None
        return True

    async def _run_task(self, t: BuildTask) -> None:
        for _attempt in range(2):  # a second go if the owner's provider fails
            if not self._ensure_people(t):
                self._task_status(t, "blocked")
                return
            self._task_status(t, "building")
            built = await self._build_turn(t, "build")
            if built is None:
                continue
            entry, files = built
            if entry.stance == Stance.QUESTION:
                await self._handle_question(t, entry)
                self._task_status(t, "building")
                built = await self._build_turn(t, "build")
                if built is None:
                    continue
                entry, files = built
            self._save_files(t, entry, files)
            break
        else:
            self._task_status(t, "blocked")
            return

        while t.review_rounds < MAX_REVIEW_ROUNDS and t.reviewer and t.reviewer in self.seat_by_letter:
            t.review_rounds += 1
            self._task_status(t, "in_review")
            review = await self._review_turn(t)
            if review is None or review.stance != Stance.CHALLENGE:
                break
            self._task_status(t, "changes")
            revised = await self._build_turn(t, "revise", feedback=review.content)
            if revised is None:
                break
            self._save_files(t, *revised)
        self._task_status(t, "done")

    def _file_context(self, paths: list[str]) -> str:
        chunks, total = [], 0
        for path in dict.fromkeys(paths):
            try:
                target = sandbox.safe_path(self.run_id, path)
            except sandbox.SandboxError:
                continue
            if not target.is_file():
                continue
            text = target.read_text(encoding="utf-8")
            if len(text) > CONTEXT_FILE_CHARS:
                text = text[:CONTEXT_FILE_CHARS] + "\n... (truncated)"
            if total + len(text) > CONTEXT_TOTAL_CHARS:
                chunks.append(f"--- {path}: (omitted, context is full)")
                continue
            total += len(text)
            chunks.append(f"--- {path}\n{text}")
        return "\n\n".join(chunks) or "(none yet)"

    def _plan_text(self) -> str:
        return "\n".join(
            f"- {t.id} {t.title} [{self._ws_title(t.workstream)}]: owner {t.owner}, reviewer {t.reviewer}, "
            f"files {', '.join(t.files)}, status {t.status}" for t in self.build_tasks
        )

    def _task_context(self, t: BuildTask, include_own: bool) -> str:
        deps = [p for d in t.depends_on for x in self.build_tasks if x.id == d for p in x.files]
        paths = deps + (t.files if include_own else [])
        return (f"{self._direction()}\n\nTASK PLAN:\n{self._plan_text()}\n\n"
                f"FILES YOU CAN SEE:\n{self._file_context(paths)}")

    async def _build_turn(self, t: BuildTask, mode: str, feedback: str = "") -> tuple[Entry, list[FileBlock]] | None:
        seat: SeatConfig = self.seat_by_letter[t.owner]
        holder: dict[str, list[FileBlock]] = {}
        files_list = ", ".join(t.files)

        def parse(text: str) -> AgentReply:
            reply, files = parse_build_reply(text)
            holder["files"] = files
            return reply

        def validate(reply: AgentReply) -> None:
            files = holder.get("files", [])
            if reply.stance == Stance.QUESTION and mode == "build" and not t.asked:
                q = reply.proposal or {}
                if not str(q.get("question", "")).strip():
                    raise ReplyError('A question needs "proposal": {"to": "<seat letter>", "question": "..."}.')
                reply.reply_to = None
                reply.votes = None
                return
            if reply.stance != Stance.REPORT:
                raise ReplyError('Use stance "report" and send your files as file blocks.')
            paths = {f.path for f in files}
            missing = [p for p in t.files if p not in paths]
            if missing:
                raise ReplyError(f"Send the complete file(s) for: {', '.join(missing)}.")
            foreign = [p for p in paths if self.file_owner.get(p, t.id) != t.id or
                       (p not in t.files and any(p in x.files for x in self.build_tasks if x is not t))]
            if foreign:
                raise ReplyError(f"Those files belong to other tasks: {', '.join(foreign)}.")
            reply.reply_to = t.entry_id if mode == "revise" else None
            reply.proposal = {"files": sorted(paths)}
            reply.votes = None

        if mode == "build":
            answer = ""
            if t.question and t.question.get("answer"):
                answer = (f"\nANSWER to your question from {t.question['to']}: {t.question['answer']}\n"
                          "You cannot ask another question; build now.")
            ask = ("" if t.asked else
                   ' If you are truly blocked and need one answer from a teammate first, reply instead with '
                   'stance "question", "proposal": {"to": "<seat letter>", "question": "..."} and no files. '
                   "You can ask once.")
            instruction = (f'Task {t.id} "{t.title}": {t.brief} Write: {files_list}.{answer}\n'
                           f'JSON: stance "report", reply_to null, content = one or two sentences on what you '
                           f"built.{ask}\n{FORMAT_HELP}")
            label = f"STEP: BUILD TASK {t.id}"
        else:
            instruction = (f'Revise task {t.id} "{t.title}" ({files_list}) to address this:\n{feedback}\n'
                           f'JSON: stance "report", reply_to "{t.entry_id}", content = what you changed. Send the '
                           f"complete updated files.\n{FORMAT_HELP}")
            label = f"STEP: REVISE TASK {t.id}"

        entry = await self._ask(
            seat, "build" if mode == "build" else "revise", label, instruction, validate,
            context=self._task_context(t, include_own=mode == "revise"),
            max_tokens=get_settings().build_max_tokens, record=False, parse=parse,
        )
        if entry is None:
            return None
        return entry, holder.get("files", [])

    def _save_files(self, t: BuildTask, entry: Entry, files: list[FileBlock]) -> None:
        t.entry_id = entry.id
        for f in files:
            new = f.path not in self._written
            self.file_owner[f.path] = t.id
            self._write_file(entry.seat, f.path, f.content)
            self._written.add(f.path)
            if new:
                self.log.emit("artifact_created", path=f.path, kind="file", task=t.id, seat=entry.seat)

    async def _handle_question(self, t: BuildTask, question: Entry) -> None:
        q = question.proposal or {}
        present = [s.letter for s in self._present()]
        to = str(q.get("to", "")).strip().upper()
        if to not in present or to == t.owner:
            # The coordinator routes it: the owner of something this task depends on, else the reviewer.
            dep_owners = [x.owner for x in self.build_tasks if x.id in t.depends_on and x.owner in present]
            to = next((c for c in dep_owners + [t.reviewer] + present if c and c != t.owner and c in present), None)
        t.asked = True
        if not to:
            return
        t.question = {"to": to, "text": str(q.get("question", "")).strip()}
        self._task_status(t, "blocked")
        self._moderator_note("board", f"Board: {t.owner} asks {to} about {t.id} {t.title}: {t.question['text']}")
        seat = self.seat_by_letter[to]

        def validate(reply: AgentReply) -> None:
            if reply.stance not in (Stance.REPORT, Stance.AGREE):
                raise ReplyError('Use stance "report" with your answer in content.')
            reply.reply_to = question.id
            reply.proposal = None
            reply.votes = None

        entry = await self._ask(
            seat, "board", "STEP: ANSWER",
            f'{t.owner} asks you about task {t.id} "{t.title}": {t.question["text"]}\n'
            f'Answer briefly and concretely. Use stance "report", reply_to "{question.id}".',
            validate, context=self._task_context(t, include_own=False), record=False,
        )
        t.question["answer"] = entry.content if entry else "(no answer: use your best judgement)"
        self._task_status(t, "blocked")

    async def _review_turn(self, t: BuildTask) -> Entry | None:
        seat = self.seat_by_letter.get(t.reviewer or "")
        if seat is None or seat.letter in self.absent:
            return None

        def validate(reply: AgentReply) -> None:
            if reply.stance not in (Stance.AGREE, Stance.CHALLENGE):
                raise ReplyError('Use stance "agree" to approve or "challenge" to ask for changes.')
            if len(reply.content.strip()) < 15:
                raise ReplyError("Be specific: say what is good, or exactly what must change.")
            reply.reply_to = t.entry_id
            reply.proposal = None
            reply.votes = None

        last_round = t.review_rounds >= MAX_REVIEW_ROUNDS
        return await self._ask(
            seat, "review", f"STEP: REVIEW TASK {t.id}",
            f'Review task {t.id} "{t.title}" by {t.owner} ({", ".join(t.files)}). Check it works, fits the '
            "plan and the other files, and serves the client. If it is good, use stance \"agree\". Otherwise "
            "use stance \"challenge\" and list the specific changes needed, quoting the code or text."
            + (" This is the final review round, so only challenge for real problems." if last_round else ""),
            validate, context=self._task_context(t, include_own=True), record=False,
        )

    # ------------------------------------------------------------ after the client's review

    def _build_summary(self) -> str:
        lines = [f"- {t.id} {t.title}: {', '.join(t.files)} (built by {t.owner}, reviewed by {t.reviewer}, "
                 f"{t.status})" for t in self.build_tasks]
        docs = [p for t in self.build_tasks for p in t.files if p.startswith("docs/")]
        return ("WHAT THE COUNCIL BUILT:\n" + "\n".join(lines)
                + (f"\n\nDOCUMENTS:\n{self._file_context(docs)}" if docs else ""))

    async def _revise_build(self, note: str) -> None:
        listing = "\n".join(f"- {t.id}: {t.title} ({', '.join(t.files)})" for t in self.build_tasks)
        data = await self._moderator_json(
            "STEP: ROUTE CHANGES",
            f'The client asked for changes: "{note}". Which tasks must change?\n{listing}\n'
            'Reply with only JSON: {"tasks": ["t1", ...]}',
            self._direction(),
        )
        ids = {t.id for t in self.build_tasks}
        chosen = [str(x) for x in (data or {}).get("tasks") or [] if str(x) in ids] or [
            t.id for t in self.build_tasks if any(p.startswith("site/") for p in t.files)
        ] or list(ids)
        self._moderator_note("board", "The client's changes go to: " + ", ".join(chosen) + ".")
        self.log.emit("phase_changed", phase=self.phase, round="revise")
        for t in self.build_tasks:
            if t.id not in chosen or not self._ensure_people(t):
                continue
            self._task_status(t, "changes")
            revised = await self._build_turn(t, "revise", feedback=f"The client asked: {note}")
            if revised:
                self._save_files(t, *revised)
            self._task_status(t, "done")


def _has_cycle(tasks: list[BuildTask]) -> bool:
    deps = {t.id: set(t.depends_on) for t in tasks}
    seen: set[str] = set()
    while True:
        ready = [t for t, d in deps.items() if t not in seen and d <= seen]
        if not ready:
            return len(seen) != len(deps)
        seen.update(ready)
