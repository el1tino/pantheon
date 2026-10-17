"""Round-based debate between seats: round limits, majority vote, moderator summary, cost tracking.

Flow: round 1 every seat proposes; later rounds seats agree, challenge, propose or question.
If every present seat agrees with the same proposal the debate ends early. Otherwise, after
the round limit, seats vote for one proposal that is not their own and the majority wins
(the moderator breaks ties). The moderator then writes a summary.
"""

import json
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from sqlmodel import Session

from app.config import APP_NAME, get_settings
from app.db import Message, Run, Seat, Vote
from app.events.log import EventLog
from app.gateway import openrouter
from app.gateway.openrouter import ChatResult, GatewayError
from app.orchestrator import sandbox
from app.orchestrator.budget import Budget, BudgetExceeded, usd
from app.orchestrator.protocol import (
    REPLY_FORMAT_HELP,
    AgentReply,
    ReplyError,
    Stance,
    extract_json,
    parse_reply,
)
from app.orchestrator.seats import SeatConfig

ChatFn = Callable[..., Awaitable[ChatResult]]
# Called when the next call would pass the cap. Return a new cap to continue, or None to stop.
PauseFn = Callable[[Budget, BudgetExceeded], Awaitable[float | None]]
Mode = Literal["open", "discuss", "vote"]

MODERATOR = "moderator"


class RunStopped(Exception):
    pass


@dataclass
class Entry:
    id: str  # short id shown to models, e.g. "m3"
    seat: str  # seat letter, or "moderator"
    round: int | str  # 1..N, "vote", or "summary"
    stance: str
    content: str
    reply_to: str | None = None
    proposal: dict[str, Any] | None = None
    votes: list[dict[str, Any]] | None = None
    tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class DebateResult:
    run_id: str
    status: str  # done | stopped | failed
    decided_by: str  # consensus | vote | moderator | none
    decision: Entry | None
    summary: str
    entries: list[Entry]
    tally: dict[str, int]
    spent_usd: float
    absent: list[str]
    dropped: int
    transcript_paths: list[str] = field(default_factory=list)


class Debate:
    def __init__(
        self,
        session: Session,
        goal: str,
        seats: list[SeatConfig],
        *,
        budget_usd: float | None = None,
        max_rounds: int | None = None,
        phase: str = "debate",
        chat: ChatFn | None = None,
        prices: dict[str, tuple[float, float]] | None = None,
        on_budget_pause: PauseFn | None = None,
        moderator_model: str | None = None,
    ):
        settings = get_settings()
        if not seats:
            raise ValueError("A debate needs at least one seat")
        self.session = session
        self.goal = goal
        self.seats = seats
        self.seat_by_letter = {s.letter: s for s in seats}
        self.max_rounds = max_rounds or settings.max_rounds
        self.phase = phase
        self.chat = chat or openrouter.chat
        self.on_budget_pause = on_budget_pause
        self.moderator_model = moderator_model or settings.moderator_model
        self.reply_max_tokens = settings.reply_max_tokens
        self.timeout = settings.call_timeout_s
        self.budget = Budget(cap_usd=budget_usd or settings.default_budget_usd, prices=prices or {})

        self.entries: list[Entry] = []
        self.by_id: dict[str, Entry] = {}
        self.absent: set[str] = set()
        self.dropped = 0
        self.tally: dict[str, int] = {}
        # Tokens and cost of the turn in progress (a turn may include one retry).
        self._turn_tokens = 0
        self._turn_cost = 0.0

        self.run = Run(
            goal=goal, status="created", phase=phase, budget_usd=self.budget.cap_usd
        )
        session.add(self.run)
        session.flush()
        for s in seats:
            session.add(
                Seat(
                    run_id=self.run.id, letter=s.letter, name=s.name, model_id=s.model_id,
                    colour=s.colour, role=s.role,
                )
            )
        session.commit()
        self.log = EventLog(session, self.run.id)

    @property
    def run_id(self) -> str:
        return self.run.id

    # ------------------------------------------------------------------ main loop

    async def run_debate(self) -> DebateResult:
        self._set_run(status="running")
        self.log.emit(
            "phase_changed", phase=self.phase, round=None, goal=self.goal,
            max_rounds=self.max_rounds, budget_usd=self.budget.cap_usd,
            seats=[
                {"letter": s.letter, "name": s.name, "colour": s.colour, "role": s.role,
                 "model_id": s.model_id}
                for s in self.seats
            ],
        )
        decision: Entry | None = None
        decided_by = "none"
        summary = ""
        status = "done"
        try:
            for r in range(1, self.max_rounds + 1):
                if self._present() == []:
                    break
                self.log.emit("phase_changed", phase=self.phase, round=r)
                replies: dict[str, Entry] = {}
                for seat in self.seats:
                    if seat.letter in self.absent:
                        continue
                    entry = await self._turn(seat, r, "open" if r == 1 else "discuss")
                    if entry:
                        replies[seat.letter] = entry
                if r > 1:
                    decision = self._consensus(replies)
                    if decision:
                        decided_by = "consensus"
                        break

            if not self._present():
                status = "failed"
            elif decision is None:
                decision, decided_by = await self._vote()
            summary = await self._summarise(decision, decided_by)
        except RunStopped:
            status = "stopped"
            summary = "The run was stopped at the budget cap before the council finished."

        self._set_run(status=status)
        self.log.emit(
            "phase_changed", phase=self.phase, round=None, status=status,
            decided_by=decided_by, decision=decision.id if decision else None,
        )
        result = DebateResult(
            run_id=self.run_id, status=status, decided_by=decided_by, decision=decision,
            summary=summary, entries=self.entries, tally=self.tally,
            spent_usd=self.budget.spent_usd, absent=sorted(self.absent), dropped=self.dropped,
        )
        result.transcript_paths = self._save_transcript(result)
        return result

    def _present(self) -> list[SeatConfig]:
        return [s for s in self.seats if s.letter not in self.absent]

    def _set_run(self, **fields: Any) -> None:
        for k, v in fields.items():
            setattr(self.run, k, v)
        self.session.add(self.run)
        self.session.commit()

    # ------------------------------------------------------------------ prompts

    def _system_prompt(self, seat: SeatConfig) -> str:
        others = ", ".join(
            f"{s.letter} {s.name} ({s.role})" for s in self.seats if s.letter != seat.letter
        )
        return (
            f"You are {seat.name}, seat {seat.letter} on the {APP_NAME} council: AI models from "
            f"different providers working on a client's goal together.\n"
            f"Your role: {seat.role}.\n"
            f"Other members: {others or 'none'}.\n"
            "Speak in your own voice and be concrete. Keep each message under 120 words. "
            "Challenge when you have a real reason; agree when a proposal is good enough.\n\n"
            f"{REPLY_FORMAT_HELP}"
        )

    def _render_entry(self, e: Entry) -> str:
        if e.seat == MODERATOR:
            head = f"[{e.id}] Moderator"
        else:
            s = self.seat_by_letter[e.seat]
            head = f"[{e.id}] {s.letter} {s.name} ({e.stance}"
            head += f" -> {e.reply_to})" if e.reply_to else ")"
        lines = [f"{head}: {e.content}"]
        if e.proposal:
            lines.append(f"     PROPOSAL: {_proposal_title(e.proposal)}")
        if e.votes:
            lines.append("     VOTES: " + ", ".join(v["target"] for v in e.votes))
        return "\n".join(lines)

    def _transcript_text(self) -> str:
        return "\n".join(self._render_entry(e) for e in self.entries) or "(nothing yet)"

    def _instruction(self, seat: SeatConfig, mode: Mode, candidates: list[Entry]) -> str:
        if mode == "open":
            return (
                'Make your opening proposal. Use stance "propose", reply_to null, and fill in '
                '"proposal" with a title and summary.'
            )
        if mode == "discuss":
            return (
                "Respond to the discussion. Choose one stance:\n"
                '- "agree" with reply_to set to the id of the proposal you back (your own counts);\n'
                '- "challenge" with reply_to set to the message you dispute;\n'
                '- "propose" a new or revised proposal (fill in "proposal");\n'
                '- "question" with reply_to set to the message you are asking about.\n'
                "If the council has converged, agree with the leading proposal so the debate can close."
            )
        options = "\n".join(
            f"- {c.id} by {c.seat}: {_proposal_title(c.proposal)}"
            for c in candidates if c.seat != seat.letter
        )
        return (
            "VOTE. The debate reached its round limit without agreement. Candidate proposals:\n"
            f"{options}\n"
            'Vote for exactly ONE proposal that is not your own: stance "vote", '
            'votes [{"target": "<id>", "score": 1}], and explain your choice in content.'
        )

    def _messages(self, seat: SeatConfig, round_: int | str, mode: Mode, candidates: list[Entry]):
        label = "VOTE ROUND" if mode == "vote" else f"ROUND {round_} of {self.max_rounds}"
        user = (
            f"GOAL: {self.goal}\n\nTRANSCRIPT SO FAR:\n{self._transcript_text()}\n\n"
            f"{label}. {self._instruction(seat, mode, candidates)}"
        )
        return [
            {"role": "system", "content": self._system_prompt(seat)},
            {"role": "user", "content": user},
        ]

    # ------------------------------------------------------------------ validation

    def _validate(self, reply: AgentReply, seat: SeatConfig, mode: Mode, candidates: list[Entry]):
        if mode == "open":
            if reply.stance != Stance.PROPOSE:
                raise ReplyError('Round 1 replies must use stance "propose".')
            if not reply.proposal:
                raise ReplyError('A "propose" reply must include a "proposal" object.')
            reply.reply_to = None
            reply.votes = None
            return
        if mode == "discuss":
            allowed = {Stance.PROPOSE, Stance.CHALLENGE, Stance.AGREE, Stance.QUESTION}
            if reply.stance not in allowed:
                raise ReplyError("Stance must be one of: propose, challenge, agree, question.")
            if reply.reply_to and reply.reply_to not in self.by_id:
                raise ReplyError(f'reply_to "{reply.reply_to}" is not a message id in the transcript.')
            if reply.stance != Stance.PROPOSE and not reply.reply_to:
                raise ReplyError(f'A "{reply.stance}" reply must set reply_to to a message id.')
            if reply.stance == Stance.PROPOSE and not reply.proposal:
                raise ReplyError('A "propose" reply must include a "proposal" object.')
            reply.votes = None
            return
        # vote
        valid = {c.id for c in candidates if c.seat != seat.letter}
        if reply.stance != Stance.VOTE:
            raise ReplyError('This is the vote round: use stance "vote".')
        if not reply.votes or len(reply.votes) != 1:
            raise ReplyError("Cast exactly one vote.")
        target = reply.votes[0].target
        if target not in valid:
            raise ReplyError(
                f'"{target}" is not a valid choice. Pick one of: {", ".join(sorted(valid))} '
                "(you cannot vote for your own proposal)."
            )
        reply.votes[0].score = 1
        reply.reply_to = target
        reply.proposal = None

    # ------------------------------------------------------------------ calls

    async def _call(self, who: str, model: str, messages: list[dict[str, str]]) -> str | None:
        """One model call under the budget. Returns None if the provider failed."""
        estimate = self.budget.estimate(model, messages, self.reply_max_tokens)
        while True:
            try:
                self.budget.check(estimate)
                break
            except BudgetExceeded as exc:
                await self._pause(exc)

        self.log.emit("seat_thinking", seat=who, state="thinking")
        try:
            res = await self.chat(
                messages, model=model, max_tokens=self.reply_max_tokens, timeout=self.timeout
            )
        except GatewayError as exc:
            if who == MODERATOR:
                self.log.emit("seat_thinking", seat=who, state="idle", error=str(exc))
            else:
                self.absent.add(who)
                self.log.emit("seat_thinking", seat=who, state="absent", error=str(exc))
            return None

        cost = self.budget.actual_cost(
            model, res.prompt_tokens, res.completion_tokens, res.cost_usd
        )
        self.budget.record(cost)
        self._turn_tokens += res.prompt_tokens + res.completion_tokens
        self._turn_cost += cost
        self._set_run(spent_usd=self.budget.spent_usd)
        self.log.emit(
            "cost_updated", spent_usd=self.budget.spent_usd, cap_usd=self.budget.cap_usd,
            ratio=self.budget.ratio, warning=self.budget.warning, last_call_usd=cost, seat=who,
        )
        return res.content

    async def _pause(self, exc: BudgetExceeded) -> None:
        self._set_run(status="paused")
        self.log.emit(
            "checkpoint_opened", kind="budget", spent_usd=exc.spent, cap_usd=exc.cap,
            next_call_estimate_usd=exc.estimate,
        )
        new_cap = await self.on_budget_pause(self.budget, exc) if self.on_budget_pause else None
        if new_cap is None or new_cap <= self.budget.cap_usd:
            self._set_run(status="stopped")
            self.log.emit("checkpoint_resolved", kind="budget", action="stop")
            raise RunStopped()
        self.budget.cap_usd = new_cap
        self._set_run(status="running", budget_usd=new_cap)
        self.log.emit("checkpoint_resolved", kind="budget", action="raise_cap", cap_usd=new_cap)

    async def _turn(
        self, seat: SeatConfig, round_: int | str, mode: Mode, candidates: list[Entry] = ()
    ) -> Entry | None:
        """Ask one seat for a reply; retry once with the error shown, then drop it."""
        self._turn_tokens, self._turn_cost = 0, 0.0
        messages = self._messages(seat, round_, mode, list(candidates))
        error = ""
        for attempt in (1, 2):
            text = await self._call(seat.letter, seat.model_id, messages)
            if text is None:
                return None
            try:
                reply = parse_reply(text)
                self._validate(reply, seat, mode, list(candidates))
                return self._add(seat.letter, round_, reply)
            except ReplyError as exc:
                error = str(exc)
                if attempt == 1:
                    self.log.emit("seat_thinking", seat=seat.letter, state="retrying", error=error)
                    messages = messages + [
                        {"role": "assistant", "content": text},
                        {"role": "user", "content": f"Your reply was rejected: {error}\n"
                         "Reply again with only the corrected JSON object."},
                    ]
        self.dropped += 1
        self.log.emit("message_done", seat=seat.letter, round=round_, dropped=True, reason=error)
        return None

    # ------------------------------------------------------------------ recording

    def _add(self, seat: str, round_: int | str, reply: AgentReply) -> Entry:
        entry = Entry(
            id=f"m{len(self.entries) + 1}", seat=seat, round=round_, stance=reply.stance.value,
            content=reply.content, reply_to=reply.reply_to, proposal=reply.proposal,
            votes=[v.model_dump() for v in reply.votes] if reply.votes else None,
            tokens=self._turn_tokens, cost_usd=self._turn_cost,
        )
        self.entries.append(entry)
        self.by_id[entry.id] = entry
        self.session.add(
            Message(
                id=self._db_id(entry.id), run_id=self.run_id, seat=seat, phase=self.phase,
                stance=entry.stance, reply_to=self._db_id(entry.reply_to), content=entry.content,
                tokens=entry.tokens, cost_usd=entry.cost_usd,
            )
        )
        self.session.commit()
        self.log.emit("message_done", **asdict(entry))
        target = self.by_id[entry.reply_to].seat if entry.reply_to else "all"
        if target in (seat, MODERATOR):
            target = "all"
        self.log.emit(
            "message_routed", message_id=entry.id, **{"from": seat}, to=target, stance=entry.stance
        )
        return entry

    def _db_id(self, short_id: str | None) -> str | None:
        return f"{self.run_id}-{short_id}" if short_id else None

    # ------------------------------------------------------------------ deciding

    def _proposal_of(self, entry_id: str | None) -> Entry | None:
        """Follow reply_to links up to the proposal a message is ultimately about."""
        seen = set()
        while entry_id and entry_id not in seen:
            seen.add(entry_id)
            e = self.by_id.get(entry_id)
            if e is None:
                return None
            if e.stance == Stance.PROPOSE:
                return e
            entry_id = e.reply_to
        return None

    def _consensus(self, replies: dict[str, Entry]) -> Entry | None:
        present = {s.letter for s in self._present()}
        if not present or set(replies) != present:
            return None
        if any(e.stance != Stance.AGREE for e in replies.values()):
            return None
        backed = [self._proposal_of(e.reply_to) for e in replies.values()]
        if backed[0] is None or any(p is not backed[0] for p in backed):
            return None
        return backed[0]

    def _candidates(self) -> list[Entry]:
        latest: dict[str, Entry] = {}
        for e in self.entries:
            if e.stance == Stance.PROPOSE:
                latest[e.seat] = e
        return list(latest.values())

    async def _vote(self) -> tuple[Entry | None, str]:
        candidates = self._candidates()
        if not candidates:
            return None, "none"
        self.log.emit("phase_changed", phase=self.phase, round="vote")
        counts: Counter[str] = Counter({c.id: 0 for c in candidates})
        for seat in self._present():
            if not any(c.seat != seat.letter for c in candidates):
                continue  # the only proposal is this seat's own
            entry = await self._turn(seat, "vote", "vote", candidates)
            if not entry or not entry.votes:
                continue
            target = entry.votes[0]["target"]
            counts[target] += 1
            self.session.add(
                Vote(run_id=self.run_id, phase=self.phase, voter_seat=seat.letter,
                     target=self._db_id(target), score=1)
            )
            self.session.commit()
            self.log.emit(
                "vote_cast", voter=seat.letter, target=target,
                target_seat=self.by_id[target].seat, score=1,
            )
        self.tally = dict(counts)
        top = max(counts.values())
        leaders = [c for c in candidates if counts[c.id] == top]
        if len(leaders) == 1:
            return leaders[0], "vote"
        return await self._tiebreak(leaders), "moderator"

    async def _tiebreak(self, tied: list[Entry]) -> Entry:
        options = "\n".join(f"- {c.id} by {c.seat}: {_proposal_title(c.proposal)}" for c in tied)
        messages = [
            {"role": "system", "content": f"You are the neutral moderator of the {APP_NAME} council."},
            {"role": "user", "content": (
                f"GOAL: {self.goal}\n\nTRANSCRIPT:\n{self._transcript_text()}\n\n"
                f"The vote is tied between:\n{options}\n"
                'Pick the strongest. Reply with only JSON: {"winner": "<id>", "reason": "<one sentence>"}'
            )},
        ]
        text = await self._call(MODERATOR, self.moderator_model, messages)
        if text:
            try:
                winner = str(json.loads(extract_json(text)).get("winner", ""))
                for c in tied:
                    if c.id == winner:
                        return c
            except (ReplyError, json.JSONDecodeError, AttributeError):
                pass
        return tied[0]  # moderator unavailable: the earliest tied proposal wins

    async def _summarise(self, decision: Entry | None, decided_by: str) -> str:
        if decision:
            outcome = (
                f"Decision: [{decision.id}] by {decision.seat}: {_proposal_title(decision.proposal)} "
                f"(reached by {decided_by})."
            )
        else:
            outcome = "No proposal was decided."
        messages = [
            {"role": "system", "content": f"You are the neutral moderator of the {APP_NAME} council."},
            {"role": "user", "content": (
                f"GOAL: {self.goal}\n\nTRANSCRIPT:\n{self._transcript_text()}\n\n{outcome}\n"
                "Write the moderator summary in Markdown, under 200 words, with the sections "
                "**Decision**, **Why**, **Open objections** and **Next steps**."
            )},
        ]
        self._turn_tokens, self._turn_cost = 0, 0.0
        text = await self._call(MODERATOR, self.moderator_model, messages)
        summary = text.strip() if text else f"**Decision**\n\n{outcome}\n\n(The moderator was unavailable.)"
        self._add(MODERATOR, "summary", AgentReply(stance=Stance.REPORT, content=summary))
        return summary

    # ------------------------------------------------------------------ transcript

    def _save_transcript(self, result: DebateResult) -> list[str]:
        data = {
            "run_id": result.run_id, "goal": self.goal, "phase": self.phase,
            "status": result.status, "decided_by": result.decided_by,
            "decision": result.decision.id if result.decision else None,
            "tally": result.tally, "spent_usd": result.spent_usd, "cap_usd": self.budget.cap_usd,
            "absent": result.absent, "dropped": result.dropped,
            "seats": [s.model_dump() for s in self.seats],
            "entries": [asdict(e) for e in result.entries],
        }
        json_path = sandbox.write_text(self.run_id, "transcript.json", json.dumps(data, indent=2))
        md_path = sandbox.write_text(self.run_id, "transcript.md", self._markdown(result))
        return [str(json_path), str(md_path)]

    def _markdown(self, result: DebateResult) -> str:
        out = [
            f"# {APP_NAME} debate · {result.run_id}", "",
            f"**Goal:** {self.goal}", "",
            (
                f"**Status:** {result.status} · **Decided by:** {result.decided_by} · "
                f"**Cost:** {usd(result.spent_usd)} of {usd(self.budget.cap_usd)}"
            ),
            "",
            "## Seats", "",
        ]
        for s in self.seats:
            mark = " (absent)" if s.letter in self.absent else ""
            out.append(f"- **{s.letter} · {s.name}**{mark}: {s.role} · `{s.model_id}`")
        current: int | str | None = None
        for e in result.entries:
            if e.round != current:
                current = e.round
                title = {"vote": "Vote", "summary": "Moderator summary"}.get(
                    str(current), f"Round {current}"
                )
                out += ["", f"## {title}", ""]
            if e.seat == MODERATOR:
                out.append(e.content)
                continue
            s = self.seat_by_letter[e.seat]
            to = f" → {e.reply_to}" if e.reply_to else ""
            out.append(f"**[{e.id}] {s.letter} · {s.name}** — _{e.stance}{to}_  ")
            out.append(e.content)
            if e.proposal:
                out.append(f"> **Proposal:** {_proposal_title(e.proposal)}")
            out.append("")
        if result.tally:
            out += ["", "## Tally", ""]
            for cid, n in sorted(result.tally.items(), key=lambda kv: -kv[1]):
                out.append(f"- {cid} ({self.by_id[cid].seat}): {n}")
        return "\n".join(out).rstrip() + "\n"


def _proposal_title(proposal: dict[str, Any] | None) -> str:
    if not proposal:
        return "(no proposal)"
    title = proposal.get("title")
    summary = proposal.get("summary")
    if title and summary:
        return f"{title}: {summary}"
    if title or summary:
        return str(title or summary)
    return json.dumps(proposal)[:200]
