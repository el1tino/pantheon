import asyncio
import json
from collections import defaultdict
from pathlib import Path

import pytest
from sqlmodel import select

from app.db import Event, Message, Vote
from app.gateway.openrouter import ChatResult, GatewayError
from app.orchestrator.debate import Debate
from app.orchestrator.seats import SeatConfig, load_seats, pick_seats

SEATS = [
    SeatConfig(letter=x, name=f"Seat{x}", provider="p", model_id=f"fake/{x.lower()}",
               colour="#ffffff", role="tester")
    for x in "ABCD"
]
PRICES = {f"fake/{x}": (1e-7, 1e-7) for x in "abcd"} | {"fake/mod": (1e-7, 1e-7)}


def propose(title):
    return json.dumps({"stance": "propose", "reply_to": None, "content": f"I propose {title}",
                       "proposal": {"title": title, "summary": "because"}})


def reply(stance, to, content="ok"):
    return json.dumps({"stance": stance, "reply_to": to, "content": content})


def vote(target):
    return json.dumps({"stance": "vote", "content": "my vote", "votes": [{"target": target}]})


class FakeChat:
    """Scripted gateway. `script(letter, kind, messages)` returns text or raises."""

    def __init__(self, script, cost=0.001):
        self.script = script
        self.cost = cost
        self.calls = defaultdict(int)

    async def __call__(self, messages, model=None, max_tokens=None, timeout=None):
        letter = model.split("/")[1].upper()
        user = messages[1]["content"]
        if model == "fake/mod":
            kind = "tiebreak" if "vote is tied" in user else "summary"
        elif "VOTE ROUND" in user:
            kind = "vote"
        else:
            kind = "round" + user.split("ROUND ")[-1].split(" ")[0]
        self.calls[(letter, kind)] += 1
        text = self.script(letter, kind, messages, self.calls[(letter, kind)])
        return ChatResult(model, text, 100, 50, self.cost)


def run(session, script, **kw):
    chat = FakeChat(script, cost=kw.pop("cost", 0.001))
    d = Debate(session, "Name a coffee startup", kw.pop("seats", SEATS), chat=chat,
               prices=PRICES, moderator_model="fake/mod", budget_usd=kw.pop("budget", 1.0), **kw)
    return d, asyncio.run(d.run_debate()), chat


def events(session, run_id):
    rows = session.exec(select(Event).where(Event.run_id == run_id).order_by(Event.seq)).all()
    return [(r.type, json.loads(r.payload_json)) for r in rows]


def test_consensus_ends_debate_early_and_saves_transcript(session):
    def script(letter, kind, messages, n):
        if kind == "round1":
            return propose(f"Idea {letter}")
        if kind == "round2":
            return reply("agree", "m1")
        return "Summary: go with Idea A"

    d, res, chat = run(session, script)
    assert res.status == "done"
    assert res.decided_by == "consensus"
    assert res.decision.id == "m1"
    assert not any(k == "round3" for _, k in chat.calls)
    assert len(res.entries) == 9  # 4 proposals + 4 agrees + summary
    msgs = session.exec(select(Message).where(Message.run_id == d.run_id)).all()
    assert len(msgs) == 9
    for p in res.transcript_paths:
        assert d.run_id in p
    md = Path(res.transcript_paths[1]).read_text()
    assert "Idea A" in md and "Moderator summary" in md
    seqs = [r.seq for r in session.exec(select(Event).where(Event.run_id == d.run_id)).all()]
    assert seqs == list(range(1, len(seqs) + 1))


def test_agree_with_a_reply_counts_for_its_proposal(session):
    def script(letter, kind, messages, n):
        if kind == "round1":
            return propose(f"Idea {letter}")  # m1..m4
        if kind == "round2":
            # A questions m1 (m5), so round 2 is not unanimous.
            return reply("question", "m1") if letter == "A" else reply("agree", "m1")
        if kind == "round3":
            # Everyone agrees with A's question m5, which resolves to proposal m1.
            return reply("agree", "m5")
        return "summary"

    _, res, _ = run(session, script)
    assert res.decided_by == "consensus"
    assert res.decision.id == "m1"


def test_invalid_reply_is_retried_once_then_dropped(session):
    def script(letter, kind, messages, n):
        if kind == "round1" and letter == "A" and n == 1:
            return "I refuse to use JSON"
        if kind == "round1" and letter == "B":
            return "still not json"
        if kind == "round1":
            assert n == 1 or "rejected" in messages[-1]["content"]
            return propose(f"Idea {letter}")
        if kind.startswith("round"):
            return reply("agree", "m1")
        return "summary"

    _, res, chat = run(session, script)
    assert chat.calls[("A", "round1")] == 2
    assert chat.calls[("B", "round1")] == 2
    assert res.dropped == 1
    assert [e.seat for e in res.entries if e.round == 1] == ["A", "C", "D"]
    assert res.decided_by == "consensus"


def test_round_limit_then_majority_vote_and_no_self_votes(session):
    def script(letter, kind, messages, n):
        if kind == "round1":
            return propose(f"Idea {letter}")
        if kind.startswith("round"):
            return reply("challenge", "m1")
        if kind == "vote":
            if letter == "A" and n == 1:
                return vote("m1")  # own proposal: rejected, retried
            return vote("m2") if letter != "B" else vote("m3")
        return "summary"

    d, res, chat = run(session, script)
    assert chat.calls[("A", "round3")] == 1
    assert chat.calls[("A", "vote")] == 2
    assert res.decided_by == "vote"
    assert res.decision.id == "m2"
    assert res.tally == {"m1": 0, "m2": 3, "m3": 1, "m4": 0}
    votes = session.exec(select(Vote).where(Vote.run_id == d.run_id)).all()
    assert len(votes) == 4 and all(v.voter_seat != "B" or v.target.endswith("m3") for v in votes)
    assert sum(1 for t, _ in events(session, d.run_id) if t == "vote_cast") == 4


def test_tie_is_broken_by_moderator(session):
    def script(letter, kind, messages, n):
        if kind == "round1":
            return propose(f"Idea {letter}")
        if kind.startswith("round"):
            return reply("challenge", "m1")
        if kind == "vote":
            return {"A": vote("m2"), "B": vote("m1"), "C": vote("m1"), "D": vote("m2")}[letter]
        if kind == "tiebreak":
            return '{"winner": "m2", "reason": "stronger"}'
        return "summary"

    _, res, _ = run(session, script, max_rounds=1)
    assert res.decided_by == "moderator"
    assert res.decision.id == "m2"


def test_failed_provider_marks_seat_absent_and_run_continues(session):
    def script(letter, kind, messages, n):
        if letter == "C":
            raise GatewayError("timeout")
        if kind == "round1":
            return propose(f"Idea {letter}")
        if kind.startswith("round"):
            return reply("agree", "m1")
        return "summary"

    d, res, chat = run(session, script)
    assert res.status == "done"
    assert res.absent == ["C"]
    assert res.decided_by == "consensus"
    assert chat.calls[("C", "round1")] == 1 and ("C", "round2") not in chat.calls
    assert ("seat_thinking", {"seat": "C", "state": "absent", "error": "timeout"}) in events(
        session, d.run_id
    )


def _always_propose(letter, kind, messages, n):
    if kind.startswith("round"):
        return propose(f"Idea {letter}{n}")
    if kind == "vote":
        return vote("m1" if letter != "A" else "m2")
    return "summary"


def test_budget_cap_pauses_and_stops_when_user_declines(session):
    # Each call really costs $0.01 but is estimated far lower, so calls run while
    # spent + estimate stays under $0.025: three calls, then the pause.
    asked = []

    async def decline(budget, exc):
        asked.append((exc.spent, exc.cap))

    d, res, chat = run(session, _always_propose, cost=0.01, budget=0.025, on_budget_pause=decline)
    assert res.status == "stopped"
    assert sum(chat.calls.values()) == 3
    assert asked == [(pytest.approx(0.03), 0.025)]
    types = [t for t, _ in events(session, d.run_id)]
    assert "checkpoint_opened" in types and "checkpoint_resolved" in types
    assert Path(res.transcript_paths[1]).read_text()  # partial transcript still saved
    warnings = [p["warning"] for t, p in events(session, d.run_id) if t == "cost_updated"]
    assert warnings == [False, True, True]  # 0.02 / 0.025 reaches 80%


def test_budget_cap_can_be_raised_to_continue(session):
    async def raise_cap(budget, exc):
        return 10.0

    _, res, _ = run(session, _always_propose, cost=0.01, budget=0.025, on_budget_pause=raise_cap)
    assert res.status == "done"
    assert res.spent_usd > 0.025


def test_seats_yaml_has_thirteen_seats():
    seats = load_seats()
    assert [s.letter for s in seats] == list("ABCDEFGHIJKLM")
    assert [s.name for s in pick_seats(["A", "D"])] == ["Claude", "DeepSeek"]
    with pytest.raises(ValueError):
        pick_seats(["Z"])
