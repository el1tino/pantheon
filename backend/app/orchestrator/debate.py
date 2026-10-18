"""Round-based debate between seats: round limits, majority vote, moderator summary, cost tracking.

Flow: round 1 every seat proposes; later rounds seats agree, challenge, propose or question.
If every present seat agrees with the same proposal the debate ends early. Otherwise, after
the round limit, seats vote for one proposal that is not their own and the majority wins
(the moderator breaks ties). The moderator then writes a summary.

Each seat keeps a running notes file and a current proposal file in projects/<run_id>/;
every write is reported as a diff_applied event so the Chamber's core can count lines.
"""

import asyncio
import contextvars
import difflib
import json
import re
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from sqlmodel import Session

from app.config import APP_NAME, get_settings
from app.db import Artifact, Message, Run, Seat, Vote
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
from app.orchestrator.streaming import ContentStreamer

ChatFn = Callable[..., Awaitable[ChatResult]]
# Called when the next call would pass the cap. Return a new cap to continue, or None to stop.
PauseFn = Callable[[Budget, BudgetExceeded], Awaitable[float | None]]
Mode = Literal["open", "discuss", "vote"]

MODERATOR = "moderator"
CLIENT = "client"  # the user, speaking into the council chat
TOKEN_FLUSH_S = 0.066  # batch streamed text into ~15 token events per second
DIFF_FEED_MAX_LINES = 40


# Claims of having done or checked something. Without evidence they are marked unverified.
CLAIM = re.compile(
    r"\b(tests?\s+(?:now\s+)?pass(?:ed|es)?|all\s+checks?\s+pass(?:ed)?|no\s+(?:more\s+)?errors"
    r"|(?:it|this|everything|the\s+site|the\s+page)\s+(?:now\s+)?works|works\s+(?:now|correctly|fine|perfectly)"
    r"|runs\s+(?:fine|correctly|cleanly|without\s+errors)|(?:is|are|been)\s+verified|checked\s+and\s+(?:it\s+)?works"
    r"|fixed\s+(?:the|all)\s+(?:bugs?|errors?))\b",
    re.I,
)

# Tokens and cost of the turn in progress (a turn may include one retry). A context variable,
# so turns running in parallel (the build phase) each keep their own count.
_TURN: contextvars.ContextVar[list | None] = contextvars.ContextVar("pantheon_turn", default=None)


class RunStopped(Exception):
    def __init__(self, reason: str = "The run was stopped before the council finished."):
        super().__init__(reason)
        self.reason = reason


class RunControl:
    """Pause, resume and stop requests from the user. Checked between turns."""

    def __init__(self) -> None:
        self._running = asyncio.Event()
        self._running.set()
        self.stop_requested = False

    @property
    def paused(self) -> bool:
        return not self._running.is_set()

    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    def stop(self) -> None:
        self.stop_requested = True
        self._running.set()

    async def wait_until_running(self) -> None:
        await self._running.wait()


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
    phase: str = ""
    unverified: bool = False  # claims success without pointing at an artifact or a passing log


Validator = Callable[[AgentReply], None]


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
        control: RunControl | None = None,
        stream_tokens: bool = True,
        mission_brief: str = "",
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
        self.control = control or RunControl()
        self.stream_tokens = stream_tokens
        self.mission_brief = mission_brief
        self.moderator_model = moderator_model or settings.moderator_model
        self.reply_max_tokens = settings.reply_max_tokens
        self.timeout = settings.call_timeout_s
        self.budget = Budget(cap_usd=budget_usd or settings.default_budget_usd, prices=prices or {})

        self.entries: list[Entry] = []
        self.by_id: dict[str, Entry] = {}
        self.absent: set[str] = set()
        self.dropped = 0
        self.tally: dict[str, int] = {}
        # Serialises budget checks so parallel calls can't jointly overshoot the cap.
        self._budget_lock = asyncio.Lock()
        self._artifact_versions: dict[str, int] = {}

        self.run = Run(
            goal=goal, status="created", phase=phase, budget_usd=self.budget.cap_usd
        )
        session.add(self.run)
        session.flush()
        for s in seats:
            session.add(
                Seat(
                    run_id=self.run.id, letter=s.letter, name=s.name, model_id=s.model_id,
                    colour=s.colour,
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
                {"letter": s.letter, "name": s.name, "colour": s.colour, "role": None,
                 "logo": s.logo, "model_id": s.model_id}
                for s in self.seats
            ],
        )
        decision: Entry | None = None
        decided_by = "none"
        summary = ""
        status = "done"
        try:
            sandbox.write_text(self.run_id, "goal.md", f"# Goal\n\n{self.goal}\n")
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
        except RunStopped as exc:
            status = "stopped"
            summary = exc.reason

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

    @staticmethod
    def _new_turn() -> None:
        _TURN.set([0, 0.0])

    @staticmethod
    def _turn_add(tokens: int, cost: float) -> None:
        turn = _TURN.get()
        if turn is None:
            turn = [0, 0.0]
            _TURN.set(turn)
        turn[0] += tokens
        turn[1] += cost

    @staticmethod
    def _turn_totals() -> tuple[int, float]:
        turn = _TURN.get() or [0, 0.0]
        return turn[0], turn[1]

    def _present(self) -> list[SeatConfig]:
        return [s for s in self.seats if s.letter not in self.absent]

    def _set_run(self, **fields: Any) -> None:
        for k, v in fields.items():
            setattr(self.run, k, v)
        self.session.add(self.run)
        self.session.commit()

    # ------------------------------------------------------------------ prompts

    def _system_prompt(self, seat: SeatConfig) -> str:
        others = ", ".join(f"{s.letter} {s.name}" for s in self.seats if s.letter != seat.letter)
        return (
            f"You are {seat.name}, seat {seat.letter} on the {APP_NAME} council: AI models from "
            f"different providers working on a client's goal together.\n"
            f"Other members: {others or 'none'}.\n"
            "Nobody has a fixed role. Later the council will decide who does what: each member "
            "puts itself forward for the work it is best at and the others vote. Show your "
            "strengths through what you contribute now.\n"
            + (f"{self.mission_brief}\n" if self.mission_brief else "")
            + "Speak in your own voice and be concrete. Keep each message under 120 words "
            "unless you are asked to write a piece of work. "
            "Challenge when you have a real reason; agree when a proposal is good enough.\n"
            "Messages from CLIENT are direct instructions from the person you work for: follow them.\n"
            "On health, legal or money topics, say plainly that you are not a professional, "
            "flag when the client should see one, and never present a guess as fact.\n\n"
            f"{REPLY_FORMAT_HELP}"
        )

    def _render_entry(self, e: Entry) -> str:
        if e.seat == MODERATOR:
            head = f"[{e.id}] Moderator"
        elif e.seat == CLIENT:
            head = f"[{e.id}] CLIENT (direct instruction)"
        else:
            s = self.seat_by_letter[e.seat]
            head = f"[{e.id}] {s.letter} {s.name} ({e.stance}"
            head += f" -> {e.reply_to})" if e.reply_to else ")"
        lines = [f"{head}: {e.content}"]
        if e.proposal and e.proposal.get("options"):
            for i, opt in enumerate(e.proposal["options"]):
                lines.append(f"     OPTION: {_proposal_title(opt)}")
        elif e.proposal:
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

    def _messages(self, seat: SeatConfig, label: str, instruction: str, context: str | None = None):
        """Prompt for one seat. `context` replaces the transcript (e.g. for anonymous scoring)."""
        body = self._transcript_text() if context is None else context
        heading = "TRANSCRIPT SO FAR" if context is None else "CONTEXT"
        user = f"GOAL: {self.goal}\n\n{heading}:\n{body}\n\n{label}. {instruction}"
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

    async def _gate(self) -> None:
        """Honour stop and pause requests. Called between turns, never mid-call."""
        if self.control.stop_requested:
            raise RunStopped("The run was stopped by the user.")
        if self.control.paused:
            self._set_run(status="paused")
            self.log.emit("phase_changed", phase=self.phase, status="paused")
            await self.control.wait_until_running()
            if self.control.stop_requested:
                raise RunStopped("The run was stopped by the user.")
            self._set_run(status="running")
            self.log.emit("phase_changed", phase=self.phase, status="running")

    def _token_sink(self, who: str, stream: str | None) -> tuple[Callable[[str], None] | None, Callable[[], None]]:
        """Build the on_delta callback that turns streamed output into batched token events."""
        if not stream or not self.stream_tokens:
            return None, lambda: None
        streamer = ContentStreamer() if stream == "json" else None
        pending: list[str] = []
        last = [time.monotonic()]

        def flush() -> None:
            if pending:
                self.log.emit("token", seat=who, text="".join(pending))
                pending.clear()
            last[0] = time.monotonic()

        def on_delta(chunk: str) -> None:
            text = streamer.feed(chunk) if streamer else chunk
            if text:
                pending.append(text)
            if time.monotonic() - last[0] >= TOKEN_FLUSH_S:
                flush()

        return on_delta, flush

    async def _call(
        self, who: str, model: str, messages: list[dict[str, str]], stream: str | None = None,
        max_tokens: int | None = None,
    ) -> str | None:
        """One model call under the budget. Returns None if the provider failed.

        stream="json" types out the reply's "content" field live; stream="text" the raw text.
        """
        max_tokens = max_tokens or self.reply_max_tokens
        estimate = self.budget.estimate(model, messages, max_tokens)
        return await self._with_budget(estimate, lambda: self._send(who, model, messages, stream, max_tokens))

    async def _with_budget(self, estimate: float, run: Callable[[], Awaitable[Any]]) -> Any:
        """Reserve the estimate under the cap (pausing to ask if it won't fit), then run."""
        async with self._budget_lock:
            while True:
                try:
                    self.budget.check(estimate)
                    break
                except BudgetExceeded as exc:
                    await self._pause(exc)
            self.budget.reserved_usd += estimate
        try:
            return await run()
        finally:
            self.budget.reserved_usd -= estimate

    def _record_cost(self, who: str, cost: float) -> None:
        self.budget.record(cost)
        self._set_run(spent_usd=self.budget.spent_usd)
        self.log.emit(
            "cost_updated", spent_usd=self.budget.spent_usd, cap_usd=self.budget.cap_usd,
            ratio=self.budget.ratio, warning=self.budget.warning, last_call_usd=cost, seat=who,
        )

    async def _send(
        self, who: str, model: str, messages: list[dict[str, str]], stream: str | None, max_tokens: int
    ) -> str | None:
        self.log.emit("seat_thinking", seat=who, state="thinking")
        on_delta, flush = self._token_sink(who, stream)
        kwargs = {"on_delta": on_delta} if on_delta else {}
        try:
            res = await self.chat(
                messages, model=model, max_tokens=max_tokens, timeout=self.timeout,
                **kwargs,
            )
            flush()
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
        self._turn_add(res.prompt_tokens + res.completion_tokens, cost)
        self._record_cost(who, cost)
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
        """One debate turn: open proposal, discussion reply or vote."""
        label = "VOTE ROUND" if mode == "vote" else f"ROUND {round_} of {self.max_rounds}"
        cands = list(candidates)
        return await self._ask(
            seat, round_, label, self._instruction(seat, mode, cands),
            lambda reply: self._validate(reply, seat, mode, cands),
        )

    async def _ask(
        self,
        seat: SeatConfig,
        round_: int | str,
        label: str,
        instruction: str,
        validate: Validator,
        *,
        context: str | None = None,
        max_tokens: int | None = None,
        record: bool = True,
        parse: Callable[[str], AgentReply] = parse_reply,
    ) -> Entry | None:
        """Ask one seat for a reply; retry once with the error shown, then drop it.

        `parse` turns the raw text into a reply (build steps also pull file blocks out of it).
        """
        await self._gate()
        self._new_turn()
        messages = self._messages(seat, label, instruction, context)
        error = ""
        for attempt in (1, 2):
            text = await self._call(
                seat.letter, seat.model_id, messages, stream="json", max_tokens=max_tokens
            )
            if text is None:
                return None
            try:
                reply = parse(text)
                validate(reply)
                return self._add(seat.letter, round_, reply, record=record)
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

    def _add(self, seat: str, round_: int | str, reply: AgentReply, record: bool = True) -> Entry:
        entry = Entry(
            id=f"m{len(self.entries) + 1}", seat=seat, round=round_, stance=reply.stance.value,
            content=reply.content, reply_to=reply.reply_to, proposal=reply.proposal,
            votes=[v.model_dump() for v in reply.votes] if reply.votes else None,
            tokens=self._turn_totals()[0], cost_usd=self._turn_totals()[1], phase=self.phase,
        )
        entry.unverified = self._unverified(entry)
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
        self._route(entry)
        if record:
            self._record_work(entry)
        return entry

    def _unverified(self, entry: Entry) -> bool:
        """The fact-checking guardrail: a claim of success must point at proof."""
        if entry.seat in (MODERATOR, CLIENT) or not CLAIM.search(entry.content):
            return False
        evidence = (entry.proposal or {}).get("evidence") or []
        return not any(self._evidence_ok(str(p)) for p in evidence if isinstance(p, str))

    def _evidence_ok(self, path: str) -> bool:
        try:
            target = sandbox.safe_path(self.run_id, path)
        except sandbox.SandboxError:
            return False
        if not target.is_file():
            return False
        if path.startswith("logs/") and path.endswith(".json"):
            try:
                return json.loads(target.read_text(encoding="utf-8")).get("status") == "passed"
            except (json.JSONDecodeError, OSError):
                return False
        return True

    def _route(self, entry: Entry) -> None:
        """message_routed drives the Chamber's lines: one per vote target, else one per message."""
        if entry.votes and entry.stance == Stance.VOTE:
            for v in entry.votes:
                target = self._vote_target_seat(v)
                if target and target != entry.seat:
                    self.log.emit(
                        "message_routed", message_id=entry.id, **{"from": entry.seat}, to=target,
                        stance=entry.stance,
                    )
            return
        target = self.by_id[entry.reply_to].seat if entry.reply_to in self.by_id else "all"
        if target in (entry.seat, MODERATOR, CLIENT):
            target = "all"
        self.log.emit(
            "message_routed", message_id=entry.id, **{"from": entry.seat}, to=target,
            stance=entry.stance,
        )

    def _vote_target_seat(self, vote: dict[str, Any]) -> str | None:
        target = vote.get("target")
        if target in self.by_id:
            return self.by_id[target].seat
        return None

    def add_client_message(self, text: str) -> Entry:
        """The user spoke into the council chat. Every later prompt includes it."""
        self._new_turn()
        return self._add(CLIENT, "client", AgentReply(stance=Stance.REPORT, content=text), record=False)

    def _record_work(self, entry: Entry) -> None:
        """Write what a message produced into the run folder: a seat's current proposal,
        its running notes, or the moderator's decision."""
        if entry.seat == MODERATOR:
            if entry.round == "summary":
                self._write_file(MODERATOR, "decision.md", entry.content.rstrip() + "\n")
            return
        if entry.stance == Stance.PROPOSE and entry.proposal and entry.proposal.get("title"):
            title = entry.proposal.get("title") or "Proposal"
            body = [f"# {title}", ""]
            for key, value in entry.proposal.items():
                if key != "title":
                    body.append(f"**{key.capitalize()}:** {value}")
            body += ["", entry.content, ""]
            self._write_file(entry.seat, f"proposals/{entry.seat}.md", "\n".join(body))
            return
        path = f"notes/{entry.seat}.md"
        old = self._read_file(path)
        to = f" -> {entry.reply_to}" if entry.reply_to else ""
        self._write_file(entry.seat, path, f"{old}- [{entry.id}] {entry.stance}{to}: {entry.content}\n")

    def _read_file(self, rel: str) -> str:
        path = sandbox.safe_path(self.run_id, rel)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _write_file(self, seat: str, rel: str, text: str) -> None:
        old = self._read_file(rel)
        sandbox.write_text(self.run_id, rel, text)
        diff = [
            line for line in difflib.unified_diff(old.splitlines(), text.splitlines(), lineterm="", n=0)
            if line[:1] in "+-" and not line.startswith(("+++", "---"))
        ]
        added = sum(1 for line in diff if line.startswith("+"))
        removed = len(diff) - added
        version = self._artifact_versions.get(rel, 0) + 1
        self._artifact_versions[rel] = version
        self.session.add(
            Artifact(run_id=self.run_id, path=rel, kind="text", version=version, created_by=seat,
                     lines_added=added, lines_removed=removed)
        )
        self.session.commit()
        self.log.emit(
            "diff_applied", seat=seat, file=rel, lines_added=added, lines_removed=removed,
            lines=[{"op": line[0], "text": line[1:]} for line in diff[:DIFF_FEED_MAX_LINES]],
        )

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
                # Only debate proposals count, not option lists or nominations for parts.
                return e if isinstance(e.round, int) and e.proposal and e.proposal.get("title") else None
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

    def _candidates(self, phases: set[str] | None = None) -> list[Entry]:
        """Latest debate proposal per seat (debate rounds only, optionally limited to phases)."""
        latest: dict[str, Entry] = {}
        for e in self.entries:
            if e.stance == Stance.PROPOSE and isinstance(e.round, int) and e.proposal:
                if phases is None or e.phase in phases:
                    latest[e.seat] = e
        return list(latest.values())

    async def _vote(self, phases: set[str] | None = None) -> tuple[Entry | None, str]:
        candidates = self._candidates(phases)
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
        await self._gate()
        self._new_turn()
        text = await self._call(MODERATOR, self.moderator_model, messages, stream="text")
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
            out.append(f"- **{s.letter} · {s.name}**{mark} · {s.provider} · `{s.model_id}`")
        current: tuple[str, int | str] | None = None
        for e in result.entries:
            if (e.phase, e.round) != current:
                current = (e.phase, e.round)
                title = {"vote": "Vote", "summary": "Moderator summary"}.get(
                    str(e.round), f"Round {e.round}" if isinstance(e.round, int) else str(e.round).capitalize()
                )
                if e.phase and e.phase != "debate":
                    title = f"{e.phase.capitalize()} · {title}"
                out += ["", f"## {title}", ""]
            if e.seat == MODERATOR:
                out.append(e.content)
                continue
            if e.seat == CLIENT:
                out.append(f"**[{e.id}] Client:** {e.content}")
                out.append("")
                continue
            s = self.seat_by_letter[e.seat]
            to = f" → {e.reply_to}" if e.reply_to else ""
            out.append(f"**[{e.id}] {s.letter} · {s.name}** — _{e.stance}{to}_  ")
            out.append(e.content)
            if e.proposal and isinstance(e.proposal.get("options"), list):
                for opt in e.proposal["options"]:
                    out.append(f"> **Option:** {_proposal_title(opt)}")
            elif e.proposal:
                out.append(f"> **Proposal:** {_proposal_title(e.proposal)}")
            out.append("")
        if result.tally:
            out += ["", "## Tally", ""]
            for cid, n in sorted(result.tally.items(), key=lambda kv: -kv[1]):
                seat = self.by_id[cid].seat if cid in self.by_id else self._vote_target_seat({"target": cid})
                out.append(f"- {cid} ({seat or '?'}): {n}")
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
