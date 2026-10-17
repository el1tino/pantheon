"""Missions: the kind of job a run does, and the phases that do it.

A mission is a list of phases; each phase is a list of steps. Steps are the reusable
building blocks every mission shares:

  open        every seat makes an opening proposal (debate round 1)
  discuss     debate rounds with early stop on consensus (and a vote, if decide=True)
  options     seats propose 1-3 options, score the others anonymously, the client picks
  consolidate the moderator merges the council's suggestions into options + criteria
  make        the work is split into parts, seats nominate themselves, the others vote,
              and each winner writes their part
  critique    reviewers point at a specific passage in someone else's part
  revise      makers rewrite their parts in answer to critiques and client notes
  verdict     the moderator assembles the deliverable
  review      the client accepts it or asks for changes (which loops back to revise)
"""

import json
import re
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.config import APP_NAME, get_settings
from app.db import Task, Vote
from app.orchestrator import sandbox
from app.orchestrator.debate import (
    CLIENT,
    MODERATOR,
    Debate,
    DebateResult,
    Entry,
    RunStopped,
)
from app.orchestrator.protocol import AgentReply, ReplyError, Stance, extract_json
from app.orchestrator.seats import SeatConfig

# Called when the run reaches a checkpoint. Gets the kind and payload, returns the answer.
CheckpointFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]

MAX_OPTION_ROUNDS = 3  # the first round plus two "another round" requests
MAX_CHANGE_REQUESTS = 5


# ---------------------------------------------------------------- definitions


@dataclass(frozen=True)
class Step:
    kind: str
    brief: str = ""
    rounds: int = 2  # discuss
    decide: bool = False  # discuss: vote if there is no consensus
    options: tuple[int, int] = (1, 3)  # options: how many each seat proposes
    single_part: str = ""  # make: skip the split and write one part with this title
    parts_from_options: bool = False  # make: one part per consolidated option (Decide)


@dataclass(frozen=True)
class Phase:
    key: str
    label: str
    steps: tuple[Step, ...] = ()
    available: bool = True


@dataclass(frozen=True)
class Mission:
    key: str
    label: str
    tagline: str
    brief: str  # added to every seat's system prompt
    deliverable: str  # title of the result
    phases: tuple[Phase, ...]
    available: bool = True

    def rail(self) -> list[dict[str, Any]]:
        return [{"key": "convene", "label": "Convene", "available": True}] + [
            {"key": p.key, "label": p.label, "available": p.available} for p in self.phases
        ]


def _review_tail(verdict_brief: str) -> tuple[Step, ...]:
    return (Step("verdict", verdict_brief), Step("review"))


MISSIONS: dict[str, Mission] = {
    m.key: m
    for m in [
        Mission(
            "ask", "Ask", "Questions, advice, explanations",
            "Mission: ASK. The client asked a question or wants advice. Answer it as well as the council can.",
            "Answer",
            (
                Phase("answer", "Answer", (Step(
                    "open", "Give your own answer to the client's question. Put a one-line answer in the "
                    "proposal title and your reasoning in its summary.",
                ),)),
                Phase("debate", "Debate", (Step("discuss", rounds=2),)),
                Phase("verdict", "Verdict", (Step(
                    "verdict", "Write the council's final answer for the client in Markdown. Lead with the "
                    "direct answer, then the reasoning, then any point where members still disagree. "
                    "Under 350 words.",
                ),)),
            ),
        ),
        Mission(
            "write", "Write", "Emails, essays, cover letters, posts, stories",
            "Mission: WRITE. The client wants a finished piece of writing.",
            "Finished text",
            (
                Phase("outline", "Outline", (Step(
                    "options", "Propose outlines for the piece: a short title for the angle and a summary of "
                    "its structure, tone and length.",
                ),)),
                Phase("draft", "Draft", (Step(
                    "make", "Split the piece into sections that can be written separately, in reading order.",
                ),)),
                Phase("critique", "Critique", (Step("critique"),)),
                Phase("revise", "Revise", (Step("revise"),) + _review_tail(
                    "Assemble the finished piece in Markdown from the parts, in order. Smooth the "
                    "transitions and keep each part's substance. Output only the piece itself."
                )),
            ),
        ),
        Mission(
            "plan", "Plan", "Trips, events, meals, workouts, budgets, schedules",
            "Mission: PLAN. The client wants a practical plan they can follow.",
            "Plan",
            (
                Phase("options", "Options", (Step(
                    "options", "Propose plan options: a short title and a summary of the approach "
                    "(budget level, pace, style, trade-offs).",
                ),)),
                Phase("detail", "Detail", (Step(
                    "make", "Split the detailed plan into sections (for example days, legs, meals or "
                    "weeks). Every section needs concrete times, costs and lists where they apply.",
                ),)),
                Phase("check", "Check", (Step("critique", "Check feasibility: timings, costs, distances, "
                                              "opening hours and the client's constraints."),
                                         Step("revise")) + _review_tail(
                    "Assemble the final plan in Markdown from the sections, in order. Keep the times, "
                    "costs and lists, and end with a short checklist. Output only the plan."
                )),
            ),
        ),
        Mission(
            "decide", "Decide", "Choosing between products, offers, options",
            "Mission: DECIDE. The client needs to choose between options and wants a clear recommendation.",
            "Recommendation",
            (
                Phase("criteria", "Criteria", (
                    Step("open", "List the options the client is choosing between (or the strongest "
                                 "candidates, if none are given) and the criteria that matter most. Put "
                                 "'Options and criteria' as the proposal title and the lists in its summary."),
                    Step("consolidate"),
                )),
                Phase("research", "Research", (Step(
                    "make", "Write a fact sheet for this option against every criterion. Mark anything "
                    "you are not sure of as unverified rather than guessing.",
                    parts_from_options=True,
                ),)),
                Phase("debate", "Debate", (
                    Step("open", "Recommend one option. Put the option's name in the proposal title and "
                                 "why in its summary."),
                    Step("discuss", rounds=2, decide=True),
                )),
                Phase("recommendation", "Recommendation", _review_tail(
                    "Write the recommendation in Markdown: a comparison table (options as rows, criteria "
                    "as columns), the council's recommendation and why, and when a different option "
                    "would be the better choice. Mark unverified facts. Output only the document."
                )),
            ),
        ),
        Mission(
            "learn", "Learn", "Understanding a topic, studying for a test",
            "Mission: LEARN. The client wants to understand a topic.",
            "Lesson",
            (
                Phase("approach", "Approach", (Step(
                    "options", "Propose ways to teach this: a short title and a summary of the angle, the "
                    "level and the main analogy or example.",
                ),)),
                Phase("lesson", "Lesson", (Step(
                    "make", "Split the lesson into sections, each with a clear explanation and a worked "
                    "example.",
                ),)),
                Phase("quiz", "Quiz", (
                    Step("make", "Write a short quiz of 5 questions on the lesson, with the answers and a "
                                 "one-line explanation for each at the end.", single_part="Quiz"),
                    Step("verdict", "Assemble the lesson sections in order, then the quiz, in Markdown. "
                                    "Output only the lesson."),
                )),
            ),
        ),
        Mission(
            "build", "Build", "Apps, websites, scripts",
            "Mission: BUILD.", "Working code",
            (Phase("ideas", "Ideas"), Phase("roles", "Roles"), Phase("build", "Build"),
             Phase("integrate", "Integrate")),
            available=False,
        ),
        Mission(
            "create", "Create", "Logos, illustrations, image sets",
            "Mission: CREATE.", "Images",
            (Phase("concepts", "Concepts"), Phase("roles", "Roles"), Phase("create", "Create")),
            available=False,
        ),
        Mission(
            "launch", "Launch", "A business from scratch",
            "Mission: LAUNCH. The client wants a business idea and, later, everything needed to launch it.",
            "Idea brief",
            (
                Phase("ideas", "Ideas", (
                    Step("options", "Propose business ideas: a short name and a summary of the customer, "
                                    "the problem, the product and how it makes money.", options=(2, 3)),
                    Step("verdict", "Write a one-page brief of the chosen idea in Markdown: name, customer, "
                                    "problem, product, how it makes money, risks and first steps. End by "
                                    "noting that research, roles and building are the next phases."),
                )),
                Phase("research", "Research", available=False),
                Phase("roles", "Roles", available=False),
                Phase("build", "Build", available=False),
                Phase("integrate", "Integrate", available=False),
            ),
        ),
    ]
}


def public_missions() -> list[dict[str, Any]]:
    return [
        {"key": m.key, "label": m.label, "tagline": m.tagline, "available": m.available}
        for m in MISSIONS.values()
    ]


# ---------------------------------------------------------------- runtime


@dataclass
class Option:
    id: str
    seat: str
    title: str
    summary: str
    entry_id: str
    scores: list[int] = field(default_factory=list)

    @property
    def average(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0


@dataclass
class Part:
    id: str
    title: str
    brief: str
    owner: str | None = None
    entry_id: str | None = None  # latest version of this part in the transcript
    task_id: str | None = None
    text: str = ""


class MissionRun(Debate):
    def __init__(self, session, goal: str, seats: list[SeatConfig], *, mission: str = "auto",
                 on_checkpoint: CheckpointFn | None = None, **kwargs):
        super().__init__(session, goal, seats, phase="convene", **kwargs)
        if mission != "auto" and (mission not in MISSIONS or not MISSIONS[mission].available):
            raise ValueError(f"Mission not available: {mission}")
        self.requested = mission
        self.mission: Mission | None = None
        self.on_checkpoint = on_checkpoint
        self.options: dict[str, Option] = {}
        self.chosen: Option | None = None
        self.parts: list[Part] = []
        self.compare: dict[str, list[str]] = {}  # Decide: consolidated options and criteria
        self.deliverable = ""
        self.decision: Entry | None = None
        self._seq = {"o": 0, "p": 0}
        self._last_verdict: Step | None = None

    # ------------------------------------------------------------ main loop

    async def run_mission(self) -> DebateResult:
        self._set_run(status="running", phase="convene")
        self.log.emit(
            "phase_changed", phase="convene", round=None, goal=self.goal,
            max_rounds=self.max_rounds, budget_usd=self.budget.cap_usd,
            seats=[{"letter": s.letter, "name": s.name, "colour": s.colour, "role": None,
                    "model_id": s.model_id} for s in self.seats],
            mission=None if self.requested == "auto" else self.requested,
            phases=MISSIONS[self.requested].rail() if self.requested != "auto" else None,
        )
        status = "done"
        summary = ""
        try:
            sandbox.write_text(self.run_id, "goal.md", f"# Goal\n\n{self.goal}\n")
            self.mission, reason = await self._choose_mission()
            self.mission_brief = self.mission.brief
            self.log.emit(
                "phase_changed", phase="convene", round=None, mission=self.mission.key,
                mission_label=self.mission.label, reason=reason, phases=self.mission.rail(),
            )
            for phase in self.mission.phases:
                if not phase.available:
                    continue
                if not self._present():
                    status = "failed"
                    break
                self.phase = phase.key
                self._set_run(phase=phase.key)
                self.log.emit("phase_changed", phase=phase.key, round=None)
                for step in phase.steps:
                    await self._run_step(step)
            summary = self.deliverable
        except RunStopped as exc:
            status = "stopped"
            summary = exc.reason

        self._set_run(status=status)
        self.log.emit(
            "phase_changed", phase=self.phase, round=None, status=status,
            decided_by="client" if self.chosen else ("consensus" if self.decision else None),
            decision=(self.chosen.entry_id if self.chosen else (self.decision.id if self.decision else None)),
            deliverable="deliverable.md" if self.deliverable else None,
        )
        result = DebateResult(
            run_id=self.run_id, status=status, decided_by="client" if self.chosen else "none",
            decision=self.by_id.get(self.chosen.entry_id) if self.chosen else self.decision,
            summary=summary, entries=self.entries, tally=self.tally,
            spent_usd=self.budget.spent_usd, absent=sorted(self.absent), dropped=self.dropped,
        )
        result.transcript_paths = self._save_transcript(result)
        return result

    async def _run_step(self, step: Step) -> None:
        handler = {
            "open": self._step_open,
            "discuss": self._step_discuss,
            "options": self._step_options,
            "consolidate": self._step_consolidate,
            "make": self._step_make,
            "critique": self._step_critique,
            "revise": self._step_revise,
            "verdict": self._step_verdict,
            "review": self._step_review,
        }[step.kind]
        await handler(step)

    # ------------------------------------------------------------ helpers

    def _next_id(self, prefix: str) -> str:
        self._seq[prefix] += 1
        return f"{prefix}{self._seq[prefix]}"

    def _moderator_note(self, round_: str, text: str) -> Entry:
        self._turn_tokens, self._turn_cost = 0, 0.0
        return self._add(MODERATOR, round_, AgentReply(stance=Stance.REPORT, content=text), record=False)

    def _client_notes(self) -> str:
        notes = [e.content for e in self.entries if e.seat == CLIENT]
        return "\n".join(f"- {n}" for n in notes)

    def _direction(self) -> str:
        """What the council has settled on so far, for prompts that skip the transcript."""
        lines = []
        if self.chosen:
            lines.append(f"Chosen direction: {self.chosen.title}: {self.chosen.summary}")
        if self.compare:
            lines.append("Options to compare: " + "; ".join(self.compare.get("options", [])))
            lines.append("Criteria: " + "; ".join(self.compare.get("criteria", [])))
        if self.decision and self.decision.proposal:
            title = self.decision.proposal.get("title", "")
            summary = self.decision.proposal.get("summary", "")
            lines.append(f"The council's decision: {title}. {summary}".strip())
        notes = self._client_notes()
        if notes:
            lines.append(f"CLIENT instructions (follow these):\n{notes}")
        return "\n".join(lines)

    def _vote_target_seat(self, vote: dict[str, Any]) -> str | None:
        target = vote.get("target")
        if target in self.options:
            return self.options[target].seat
        if vote.get("part") and target in self.seat_by_letter:
            return target
        return super()._vote_target_seat(vote)

    async def _moderator_json(self, label: str, instruction: str, context: str) -> dict[str, Any] | None:
        messages = [
            {"role": "system", "content": f"You are the neutral moderator of the {APP_NAME} council."},
            {"role": "user", "content": f"GOAL: {self.goal}\n\n{context}\n\n{label}. {instruction}"},
        ]
        await self._gate()
        self._turn_tokens, self._turn_cost = 0, 0.0
        text = await self._call(MODERATOR, self.moderator_model, messages)
        if not text:
            return None
        try:
            data = json.loads(extract_json(text))
            return data if isinstance(data, dict) else None
        except (ReplyError, json.JSONDecodeError):
            return None

    async def _checkpoint(self, kind: str, **payload: Any) -> dict[str, Any]:
        await self._gate()
        self._set_run(status="checkpoint")
        self.log.emit("checkpoint_opened", kind=kind, phase=self.phase, **payload)
        if self.on_checkpoint:
            answer = await self.on_checkpoint(kind, payload)
        elif kind == "pick":
            answer = {"action": "pick", "option": payload["options"][0]["id"]}
        else:
            answer = {"action": "accept"}
        if answer.get("action") == "stop":
            self.log.emit("checkpoint_resolved", kind=kind, action="stop")
            raise RunStopped("The run was stopped by the user.")
        self._set_run(status="running")
        self.log.emit("checkpoint_resolved", kind=kind, **answer)
        return answer

    # ------------------------------------------------------------ convene

    async def _choose_mission(self) -> tuple[Mission, str]:
        if self.requested != "auto":
            m = MISSIONS[self.requested]
            self._moderator_note("mission", f"Mission: {m.label}, chosen by the client.")
            return m, "Chosen by the client."
        menu = "\n".join(
            f"- {m.key}: {m.tagline}" for m in MISSIONS.values()
        )
        data = await self._moderator_json(
            "STEP: DETECT",
            "Pick the mission that best fits the goal. Reply with only JSON: "
            '{"mission": "<key>", "reason": "<one sentence>"}',
            f"MISSIONS:\n{menu}",
        )
        key = str((data or {}).get("mission", "")).strip().lower()
        reason = str((data or {}).get("reason", "")).strip() or "It fits the goal best."
        if key in MISSIONS and not MISSIONS[key].available:
            reason = f"{MISSIONS[key].label} isn't available yet, so the council will plan it instead."
            key = "plan"
        if key not in MISSIONS:
            key, reason = "ask", "The goal reads as a question, so the council will answer it."
        m = MISSIONS[key]
        self._moderator_note("mission", f"Mission: {m.label}. {reason}")
        return m, reason

    # ------------------------------------------------------------ debate steps

    async def _step_open(self, step: Step) -> None:
        self.max_rounds = 1 + 2  # label shows "ROUND 1 of 3" when a discuss step follows
        self.log.emit("phase_changed", phase=self.phase, round=1)
        instruction = (
            f'{step.brief} Use stance "propose", reply_to null, and fill in "proposal" with a '
            '"title" and a "summary".'
        )
        for seat in self._present():
            await self._ask(seat, 1, f"ROUND 1 of {self.max_rounds}", instruction,
                            lambda r, s=seat: self._validate(r, s, "open", []))

    async def _step_discuss(self, step: Step) -> None:
        self.max_rounds = 1 + step.rounds
        for r in range(2, 2 + step.rounds):
            if not self._present():
                return
            self.log.emit("phase_changed", phase=self.phase, round=r)
            replies: dict[str, Entry] = {}
            for seat in self._present():
                entry = await self._turn(seat, r, "discuss")
                if entry:
                    replies[seat.letter] = entry
            decision = self._consensus(replies)
            if decision:
                self.decision = decision
                self._moderator_note("consensus", f"The council agrees on {decision.id}: "
                                                  f"{decision.proposal.get('title') if decision.proposal else ''}.")
                return
        if step.decide:
            decision, how = await self._vote(phases={self.phase})
            if decision:
                self.decision = decision
                title = decision.proposal.get("title") if decision.proposal else decision.id
                self._moderator_note("vote", f"Decided by {'vote' if how == 'vote' else 'the moderator'}: {title}.")

    async def _step_consolidate(self, step: Step) -> None:
        data = await self._moderator_json(
            "STEP: CONSOLIDATE",
            "Merge the council's suggestions into one list of the options to compare (at most 4) and "
            'the criteria that matter. Reply with only JSON: {"options": ["..."], "criteria": ["..."]}',
            f"TRANSCRIPT:\n{self._transcript_text()}",
        )
        options = [str(o) for o in (data or {}).get("options", []) if str(o).strip()][:4]
        criteria = [str(c) for c in (data or {}).get("criteria", []) if str(c).strip()][:8]
        if not options:
            options = [e.proposal.get("title", "Option") for e in self._candidates({self.phase})][:4] or ["Option A"]
        self.compare = {"options": options, "criteria": criteria}
        self._moderator_note(
            "criteria",
            "Comparing: " + ", ".join(options) + (". Criteria: " + ", ".join(criteria) if criteria else ""),
        )

    # ------------------------------------------------------------ options + scoring + pick

    async def _step_options(self, step: Step) -> None:
        lo, hi = step.options
        for attempt in range(1, MAX_OPTION_ROUNDS + 1):
            self.log.emit("phase_changed", phase=self.phase, round="options")
            again = (
                " The client asked for another round: the options so far were not right. Propose new, "
                "different ones." if attempt > 1 else ""
            )
            instruction = (
                f"{step.brief} Propose {lo} to {hi} options.{again} Use stance \"propose\", reply_to "
                'null, and "proposal": {"options": [{"title": "...", "summary": "..."}]}.'
            )
            fresh: list[Option] = []
            for seat in self._present():
                def validate(reply: AgentReply) -> None:
                    if reply.stance != Stance.PROPOSE:
                        raise ReplyError('Use stance "propose".')
                    opts = (reply.proposal or {}).get("options")
                    if not isinstance(opts, list) or not lo <= len(opts) <= hi:
                        raise ReplyError(f'"proposal" must hold "options": a list of {lo} to {hi} items.')
                    for o in opts:
                        if not isinstance(o, dict) or not str(o.get("title", "")).strip():
                            raise ReplyError('Every option needs a "title" and a "summary".')
                    reply.reply_to = None
                    reply.votes = None

                entry = await self._ask(seat, "options", "STEP: OPTIONS", instruction, validate, record=False)
                if not entry:
                    continue
                lines = []
                for o in entry.proposal["options"]:
                    opt = Option(self._next_id("o"), seat.letter, str(o["title"]).strip(),
                                 str(o.get("summary", "")).strip(), entry.id)
                    self.options[opt.id] = opt
                    fresh.append(opt)
                    lines.append(f"## {opt.id}: {opt.title}\n\n{opt.summary}\n")
                self._write_file(seat.letter, f"options/{seat.letter}.md", "\n".join(lines))
            if not fresh:
                raise RunStopped("No seat produced an option, so the run cannot continue.")
            await self._score(fresh)
            ranked = sorted(fresh, key=lambda o: (-o.average, fresh.index(o)))
            top = ranked[:3]
            answer = await self._checkpoint(
                "pick",
                options=[{"id": o.id, "title": o.title, "summary": o.summary, "seat": o.seat,
                          "score": round(o.average, 2), "votes": len(o.scores)} for o in top],
                can_retry=attempt < MAX_OPTION_ROUNDS,
            )
            if answer.get("action") == "another_round" and attempt < MAX_OPTION_ROUNDS:
                self._moderator_note("options", "The client asked for another round of options.")
                continue
            chosen = self.options.get(str(answer.get("option"))) or top[0]
            self.chosen = chosen
            self._moderator_note(
                "pick", f"The client chose {chosen.id}: {chosen.title}. {chosen.summary}"
            )
            self._write_file(MODERATOR, "chosen.md", f"# {chosen.title}\n\n{chosen.summary}\n")
            return

    async def _score(self, options: list[Option]) -> None:
        """Every seat scores the others' options 1-5. Authors are hidden from the scorers."""
        self.log.emit("phase_changed", phase=self.phase, round="score")
        notes = self._client_notes()
        for seat in self._present():
            to_score = [o for o in options if o.seat != seat.letter]
            if not to_score:
                continue
            ids = {o.id for o in to_score}
            context = "OPTIONS (authors hidden):\n" + "\n".join(
                f"- {o.id}: {o.title}: {o.summary}" for o in to_score
            )
            if notes:
                context += f"\n\nCLIENT instructions (follow these):\n{notes}"
            instruction = (
                "Score every option above from 1 (weak) to 5 (excellent) for how well it serves the "
                'goal. Use stance "vote" and "votes": [{"target": "<option id>", "score": <1-5>}] with '
                "exactly one entry per option, and explain your scoring briefly in content."
            )

            def validate(reply: AgentReply, ids=ids) -> None:
                if reply.stance != Stance.VOTE:
                    raise ReplyError('Use stance "vote".')
                got = [v.target for v in reply.votes or []]
                if sorted(got) != sorted(ids):
                    raise ReplyError(f"Score each of these exactly once: {', '.join(sorted(ids))}.")
                for v in reply.votes:
                    if not 1 <= v.score <= 5:
                        raise ReplyError("Scores must be whole numbers from 1 to 5.")
                reply.reply_to = None
                reply.proposal = None

            entry = await self._ask(seat, "score", "STEP: SCORE", instruction, validate,
                                    context=context, record=False)
            if not entry:
                continue
            for v in entry.votes or []:
                opt = self.options[v["target"]]
                opt.scores.append(v["score"])
                self.session.add(Vote(run_id=self.run_id, phase=self.phase, voter_seat=seat.letter,
                                      target=opt.id, score=v["score"]))
                self.log.emit("vote_cast", voter=seat.letter, target=opt.id, target_seat=opt.seat,
                              score=v["score"], kind="score")
            self.session.commit()
        for o in options:
            self.tally[o.id] = round(o.average, 2)

    # ------------------------------------------------------------ make: split, nominate, vote, write

    async def _step_make(self, step: Step) -> None:
        parts = await self._split(step)
        self.parts.extend(parts)
        await self._assign(parts)
        self.log.emit("phase_changed", phase=self.phase, round="write")
        for part in parts:
            await self._write_part(part, step)

    async def _split(self, step: Step) -> list[Part]:
        if step.single_part:
            return [Part(self._next_id("p"), step.single_part, step.brief)]
        if step.parts_from_options and self.compare.get("options"):
            parts = [Part(self._next_id("p"), name, step.brief) for name in self.compare["options"]]
        else:
            k = max(1, min(4, len(self._present())))
            data = await self._moderator_json(
                "STEP: SPLIT",
                f"{step.brief} Split the work into 1 to {k} parts that different members can write "
                'independently. Reply with only JSON: {"parts": [{"title": "...", "brief": "one or two '
                'sentences"}]}',
                self._direction() or "(no direction chosen yet)",
            )
            raw = (data or {}).get("parts") or []
            parts = [
                Part(self._next_id("p"), str(p.get("title", "")).strip() or f"Part {i + 1}",
                     str(p.get("brief", "")).strip())
                for i, p in enumerate(raw[:k]) if isinstance(p, dict)
            ] or [Part(self._next_id("p"), self.mission.deliverable if self.mission else "The work", step.brief)]
        self._moderator_note(
            "split", "The work splits into: " + "; ".join(f"{p.id} {p.title}" for p in parts) + "."
        )
        return parts

    async def _assign(self, parts: list[Part]) -> None:
        """Seats put themselves forward for parts; the others vote; the winners take them."""
        present = self._present()
        ids = [p.id for p in parts]
        listing = "\n".join(f"- {p.id}: {p.title}. {p.brief}" for p in parts)
        self.log.emit("phase_changed", phase=self.phase, round="nominate")
        nominees: dict[str, list[str]] = {p.id: [] for p in parts}
        for seat in present:
            def validate(reply: AgentReply) -> None:
                if reply.stance != Stance.PROPOSE:
                    raise ReplyError('Use stance "propose".')
                chosen = (reply.proposal or {}).get("parts")
                if not isinstance(chosen, list) or any(str(x) not in ids for x in chosen):
                    raise ReplyError(f'"proposal" must hold "parts": a list of part ids from {ids}.')
                reply.reply_to = None
                reply.votes = None

            entry = await self._ask(
                seat, "nominate", "STEP: NOMINATE",
                f"The work is split into these parts:\n{listing}\n"
                "Put yourself forward for the parts you would do best and say why in one or two "
                'sentences. Use stance "propose", reply_to null, and "proposal": {"parts": ["p1", ...], '
                '"pitch": "..."}. An empty list means you would rather review.',
                validate, record=False,
            )
            if entry:
                for pid in entry.proposal.get("parts", []):
                    nominees[str(pid)].append(seat.letter)

        def candidates(part: Part) -> list[str]:
            present_letters = [s.letter for s in self._present()]
            return [x for x in nominees[part.id] if x in present_letters] or present_letters

        contested = [p for p in parts if len(candidates(p)) > 1]
        votes: dict[str, Counter[str]] = {p.id: Counter() for p in parts}
        if contested:
            self.log.emit("phase_changed", phase=self.phase, round="roles")
        for seat in self._present() if contested else []:
            mine = {p.id: [c for c in candidates(p) if c != seat.letter] for p in contested}
            mine = {pid: c for pid, c in mine.items() if c}
            if not mine:
                continue
            ballot = "\n".join(
                f"- {pid} ({next(p.title for p in parts if p.id == pid)}): {', '.join(c)}"
                for pid, c in mine.items()
            )

            def validate(reply: AgentReply, mine=mine) -> None:
                if reply.stance != Stance.VOTE:
                    raise ReplyError('Use stance "vote".')
                got = {v.part: v.target.strip().upper() for v in reply.votes or [] if v.part}
                if set(got) != set(mine):
                    raise ReplyError(f"Vote once for each part: {', '.join(mine)}.")
                for pid, target in got.items():
                    if target not in mine[pid]:
                        raise ReplyError(f"For {pid} pick one of {', '.join(mine[pid])} (not yourself).")
                reply.votes = [v.model_copy(update={"target": v.target.strip().upper()}) for v in reply.votes
                               if v.part in mine]
                reply.reply_to = None
                reply.proposal = None

            entry = await self._ask(
                seat, "roles", "STEP: ROLE VOTE",
                f"Vote for who should do each part. Candidates per part:\n{ballot}\n"
                'You cannot vote for yourself. Use stance "vote" and "votes": [{"part": "<part id>", '
                '"target": "<seat letter>"}], one per part listed, and say why briefly in content.',
                validate, record=False,
            )
            for v in (entry.votes if entry else None) or []:
                votes[v["part"]][v["target"]] += 1
                self.session.add(Vote(run_id=self.run_id, phase=self.phase, voter_seat=seat.letter,
                                      target=f"{v['part']}:{v['target']}", score=1))
                self.log.emit("vote_cast", voter=seat.letter, target=v["target"], target_seat=v["target"],
                              part=v["part"], score=1, kind="role")
            self.session.commit()

        load: Counter[str] = Counter()
        summary = []
        for part in parts:
            cands = candidates(part)
            owner = max(cands, key=lambda c: (votes[part.id][c], -load[c], -cands.index(c)))
            load[owner] += 1
            part.owner = owner
            task = Task(run_id=self.run_id, title=part.title, owner_seat=owner, status="assigned")
            self.session.add(task)
            self.session.commit()
            part.task_id = task.id
            self._task_event(part, "assigned", votes=votes[part.id][owner])
            n = votes[part.id][owner]
            summary.append(f"{part.id} {part.title} → {owner}" + (f" ({n} vote{'s' if n != 1 else ''})" if n else ""))
        self._moderator_note("roles", "Roles by vote: " + "; ".join(summary) + ".")

    def _task_event(self, part: Part, status: str, **extra: Any) -> None:
        if part.task_id:
            task = self.session.get(Task, part.task_id)
            if task:
                task.status = status
                task.owner_seat = part.owner
                self.session.add(task)
                self.session.commit()
        self.log.emit("task_updated", task_id=part.task_id, part=part.id, title=part.title,
                      owner_seat=part.owner, status=status, **extra)

    def _parts_text(self) -> str:
        return "\n\n".join(
            f"### {p.id}: {p.title} (by {p.owner})\n{p.text or '(not written yet)'}" for p in self.parts
        )

    async def _write_part(self, part: Part, step: Step) -> None:
        tried: set[str] = set()
        while True:
            seat = self.seat_by_letter.get(part.owner or "")
            if seat is None or seat.letter in self.absent or seat.letter in tried:
                # The owner is gone: hand the part to the present seat with the least work.
                spare = [s for s in self._present() if s.letter not in tried]
                if not spare:
                    self._task_event(part, "blocked")
                    return
                load = Counter(p.owner for p in self.parts)
                seat = min(spare, key=lambda s: load[s.letter])
                part.owner = seat.letter
                self._task_event(part, "reassigned")
            tried.add(seat.letter)
            self._task_event(part, "doing")
            others = "\n".join(f"- {p.id}: {p.title} (by {p.owner})" for p in self.parts if p is not part)
            context = f"{self._direction()}\n\nOTHER PARTS:\n{others or '(none)'}"
            entry = await self._ask(
                seat, "write", f"STEP: WRITE PART {part.id}",
                f'Write part {part.id} "{part.title}": {part.brief} {step.brief} Use stance "report", '
                'reply_to null, and put the full text of your part, in Markdown, in "content". Write only '
                "your part; others are writing the rest.",
                self._validate_work(None), context=context, max_tokens=get_settings().make_max_tokens,
                record=False,
            )
            if entry:
                self._save_part(part, entry)
                self._task_event(part, "done")
                return

    def _validate_work(self, reply_to: str | None):
        def validate(reply: AgentReply) -> None:
            if reply.stance != Stance.REPORT:
                raise ReplyError('Use stance "report" with the full text in "content".')
            if len(reply.content.strip()) < 40:
                raise ReplyError('"content" must hold the full text of your part.')
            reply.reply_to = reply_to
            reply.proposal = None
            reply.votes = None
        return validate

    def _save_part(self, part: Part, entry: Entry) -> None:
        part.entry_id = entry.id
        part.text = entry.content
        self._write_file(entry.seat, f"work/{part.id}-{_slug(part.title)}.md",
                         f"# {part.title}\n\n{entry.content.strip()}\n")

    # ------------------------------------------------------------ critique + revise

    async def _step_critique(self, step: Step) -> None:
        written = [p for p in self.parts if p.entry_id]
        if not written:
            return
        self.log.emit("phase_changed", phase=self.phase, round="critique")
        focus = f" Focus on: {step.brief}" if step.brief else ""
        for seat in self._present():
            targets = {p.entry_id: p for p in written if p.owner != seat.letter}
            if not targets:
                continue
            listing = "\n".join(f"- {mid}: {p.id} {p.title} (by {p.owner})" for mid, p in targets.items())

            def validate(reply: AgentReply, targets=targets) -> None:
                if reply.stance not in (Stance.CHALLENGE, Stance.AGREE):
                    raise ReplyError('Use stance "challenge" (or "agree" if the part is excellent).')
                if reply.reply_to not in targets:
                    raise ReplyError(f"reply_to must be one of: {', '.join(targets)} (not your own part).")
                if len(reply.content.strip()) < 20:
                    raise ReplyError("Point at a specific passage and say how to fix it.")
                reply.proposal = None
                reply.votes = None

            await self._ask(
                seat, "critique", "STEP: CRITIQUE",
                f"Review the work. Parts and their message ids:\n{listing}\n"
                "Pick the part that most needs improving (not your own). Quote the specific passage, say "
                f"what is wrong and how to fix it.{focus} Use stance \"challenge\" with reply_to set to "
                'that part\'s message id. If it is already excellent, use "agree" but stay specific.',
                validate, context=f"{self._direction()}\n\nTHE WORK:\n{self._parts_text()}",
            )

    async def _step_revise(self, step: Step, force: bool = False) -> None:
        if not any(p.entry_id for p in self.parts):
            return
        self.log.emit("phase_changed", phase=self.phase, round="revise")
        for part in self.parts:
            if not part.entry_id:
                continue
            feedback = [e for e in self.entries if e.reply_to == part.entry_id and e.seat != part.owner]
            if not feedback and not force:
                continue
            seat = self.seat_by_letter.get(part.owner or "")
            if seat is None or seat.letter in self.absent:
                continue
            notes = "\n".join(f"- {self.seat_by_letter[e.seat].name} ({e.stance}): {e.content}"
                              for e in feedback if e.seat in self.seat_by_letter)
            self._task_event(part, "revising")
            entry = await self._ask(
                seat, "revise", f"STEP: REVISE PART {part.id}",
                f'Revise your part {part.id} "{part.title}" using the feedback below and any CLIENT '
                f'instructions.\nFEEDBACK:\n{notes or "(none: apply the CLIENT instructions)"}\n'
                f'Use stance "report", reply_to "{part.entry_id}", and put the full revised text in '
                '"content".',
                self._validate_work(part.entry_id),
                context=f"{self._direction()}\n\nYOUR CURRENT TEXT:\n{part.text}",
                max_tokens=get_settings().make_max_tokens, record=False,
            )
            if entry:
                self._save_part(part, entry)
                self._task_event(part, "done")

    # ------------------------------------------------------------ verdict + review

    async def _step_verdict(self, step: Step) -> None:
        await self._gate()
        self._last_verdict = step
        self.log.emit("phase_changed", phase=self.phase, round="verdict")
        if self.parts:
            work = f"THE WORK, PART BY PART:\n{self._parts_text()}"
        else:
            work = f"TRANSCRIPT:\n{self._transcript_text()}"
        messages = [
            {"role": "system", "content": f"You are the neutral moderator of the {APP_NAME} council. "
                                          "On health, legal or money topics, say plainly that this is "
                                          "not professional advice and flag when to see a professional."},
            {"role": "user", "content": f"GOAL: {self.goal}\n\n{self._direction()}\n\n{work}\n\n"
                                        f"STEP: VERDICT. {step.brief} Output only the final Markdown, "
                                        "with no preamble."},
        ]
        self._turn_tokens, self._turn_cost = 0, 0.0
        text = await self._call(MODERATOR, self.moderator_model, messages, stream="text",
                                max_tokens=get_settings().verdict_max_tokens)
        if not text:
            text = "\n\n".join(f"## {p.title}\n\n{p.text}" for p in self.parts) or (
                "The moderator was unavailable, so the council's work is in the transcript."
            )
        self.deliverable = text.strip() + "\n"
        self._add(MODERATOR, "verdict", AgentReply(stance=Stance.REPORT, content=self.deliverable), record=False)
        self._write_file(MODERATOR, "deliverable.md", self.deliverable)
        title = self.mission.deliverable if self.mission else "Result"
        self.log.emit("artifact_created", path="deliverable.md", kind="deliverable", title=title,
                      content=self.deliverable)

    async def _step_review(self, step: Step) -> None:
        for _ in range(MAX_CHANGE_REQUESTS + 1):
            answer = await self._checkpoint(
                "review", path="deliverable.md", title=self.mission.deliverable if self.mission else "Result",
                content=self.deliverable,
            )
            if answer.get("action") != "changes":
                return
            note = str(answer.get("note", "")).strip() or "Please improve it."
            self.add_client_message(f"Changes requested: {note}")
            await self._step_revise(step, force=True)
            await self._step_verdict(self._last_verdict or Step("verdict"))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "part"
