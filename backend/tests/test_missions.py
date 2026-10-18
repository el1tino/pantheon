"""Milestone 4: missions, anonymous scoring, role votes, checkpoints and client messages."""

import asyncio
import json
import re
import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.db import Task, Vote
from app.devtools.council_script import reply
from app.gateway import openrouter
from app.gateway.openrouter import ChatResult, GatewayError
from app.orchestrator.missions import MissionRun
from tests.conftest import login
from tests.test_debate import PRICES, SEATS, events


class ScriptChat:
    """Gateway stand-in that answers every prompt with the scripted council."""

    def __init__(self, fail=()):
        self.prompts: list[tuple[str, str, str]] = []
        self.fail = set(fail)

    async def __call__(self, messages, model=None, max_tokens=None, timeout=None, on_delta=None):
        if model in self.fail:
            raise GatewayError("provider down")
        system = messages[0]["content"]
        user = next(m["content"] for m in messages if m["role"] == "user")
        self.prompts.append((model, system, user))
        text = reply(system, user)
        if on_delta:
            for i in range(0, len(text), 9):
                on_delta(text[i : i + 9])
        return ChatResult(model, text, 120, 60, 0.0001)

    def steps(self, name: str) -> list[tuple[str, str, str]]:
        return [p for p in self.prompts if f"STEP: {name}" in p[2]]


def run_mission(session, goal, mission="auto", on_checkpoint=None, chat=None, seats=SEATS):
    chat = chat or ScriptChat()
    m = MissionRun(session, goal, seats, mission=mission, chat=chat, prices=PRICES,
                   moderator_model="fake/mod", budget_usd=5, on_checkpoint=on_checkpoint)
    return m, asyncio.run(m.run_mission()), chat


@pytest.mark.parametrize(
    ("goal", "expected"),
    [
        ("Write a cover letter for a barista job", "write"),
        ("Plan a two day trip to Lisbon on a budget", "plan"),
        ("Should I buy a Kindle or a Kobo?", "decide"),
        ("Help me study photosynthesis for my exam", "learn"),
        ("Why is the sky blue?", "ask"),
        ("Come up with a business idea we could launch", "launch"),
    ],
)
def test_auto_detects_and_delivers_each_mission(session, goal, expected):
    m, res, _ = run_mission(session, goal)
    assert res.status == "done", res.summary
    assert m.mission.key == expected
    evs = events(session, m.run_id)
    rails = [p["phases"] for t, p in evs if t == "phase_changed" and p.get("phases")]
    assert [x["key"] for x in rails[-1]][0] == "convene"
    artifacts = [p for t, p in evs if t == "artifact_created"]
    assert artifacts and artifacts[-1]["path"] == "deliverable.md"
    from app.orchestrator import sandbox

    assert sandbox.safe_path(m.run_id, "deliverable.md").read_text().strip()
    assert evs[-1][1]["status"] == "done"


def test_scoring_is_anonymous_and_never_scores_own_options(session):
    m, res, chat = run_mission(session, "Write a toast for my sister's wedding", mission="write")
    assert res.status == "done"
    scores = chat.steps("SCORE")
    assert scores
    for _, system, user in scores:
        letter = re.search(r"seat ([A-M]) on the", system).group(1)
        listed = set(re.findall(r"^- (o\d+):", user, re.M))
        assert listed and all(m.options[o].seat != letter for o in listed)
        context = user.split("CONTEXT:")[1].split("STEP: SCORE")[0]
        # No author or seat names next to the options, and no transcript.
        assert "TRANSCRIPT" not in user and "(by " not in context
        for seat in SEATS:
            assert seat.name not in context
    votes = session.exec(select(Vote).where(Vote.run_id == m.run_id, Vote.target.startswith("o"))).all()
    assert votes and all(m.options[v.target].seat != v.voter_seat for v in votes)
    assert all(1 <= v.score <= 5 for v in votes)


def test_role_votes_assign_every_part_and_nobody_votes_for_themselves(session):
    m, res, _ = run_mission(session, "Plan a weekend of hiking near Lyon", mission="plan")
    assert res.status == "done"
    tasks = session.exec(select(Task).where(Task.run_id == m.run_id)).all()
    assert tasks and all(t.owner_seat in {"A", "B", "C", "D"} for t in tasks)
    assert all(t.status == "done" for t in tasks)
    role_votes = session.exec(select(Vote).where(Vote.run_id == m.run_id, Vote.target.startswith("p"))).all()
    assert all(v.target.split(":")[1] != v.voter_seat for v in role_votes)
    updates = [p for t, p in events(session, m.run_id) if t == "task_updated"]
    assert {u["status"] for u in updates} >= {"assigned", "doing", "done"}
    # Every part file exists and the core saw lines added.
    diffs = [p for t, p in events(session, m.run_id) if t == "diff_applied" and p["file"].startswith("work/")]
    assert diffs and sum(d["lines_added"] for d in diffs) > 0


def test_pick_checkpoint_waits_and_another_round_brings_new_options(session):
    answers = []

    async def on_checkpoint(kind, payload):
        answers.append((kind, payload))
        if kind == "pick" and len([a for a in answers if a[0] == "pick"]) == 1:
            assert payload["can_retry"] is True and len(payload["options"]) <= 3
            return {"action": "another_round"}
        if kind == "pick":
            return {"action": "pick", "option": payload["options"][-1]["id"]}
        return {"action": "accept"}

    m, res, chat = run_mission(session, "Write a short story about a lighthouse", mission="write",
                               on_checkpoint=on_checkpoint)
    assert res.status == "done"
    picks = [p for k, p in answers if k == "pick"]
    assert len(picks) == 2
    first_ids = {o["id"] for o in picks[0]["options"]}
    assert m.chosen.id == picks[1]["options"][-1]["id"] and m.chosen.id not in first_ids
    assert any("another round" in u for _, _, u in chat.steps("OPTIONS"))
    resolved = [p for t, p in events(session, m.run_id) if t == "checkpoint_resolved"]
    assert [r["action"] for r in resolved] == ["another_round", "pick", "accept"]


def test_review_changes_loop_revises_and_redelivers(session):
    reviews = []

    async def on_checkpoint(kind, payload):
        if kind == "pick":
            return {"action": "pick", "option": payload["options"][0]["id"]}
        reviews.append(payload)
        if len(reviews) == 1:
            return {"action": "changes", "note": "Make it warmer and shorter"}
        return {"action": "accept"}

    m, res, chat = run_mission(session, "Write an email asking my landlord to fix the heating",
                               mission="write", on_checkpoint=on_checkpoint)
    assert res.status == "done" and len(reviews) == 2
    assert any(e.seat == "client" and "warmer and shorter" in e.content for e in m.entries)
    revised = [u for _, _, u in chat.steps("REVISE PART") if "warmer and shorter" in u]
    assert revised
    artifacts = [p for t, p in events(session, m.run_id) if t == "artifact_created"]
    assert len(artifacts) == 2


def test_client_message_reaches_every_later_prompt(session):
    holder = {}

    async def on_checkpoint(kind, payload):
        if kind == "pick":
            holder["m"].add_client_message("Keep it under 100 words, please.")
            return {"action": "pick", "option": payload["options"][0]["id"]}
        return {"action": "accept"}

    chat = ScriptChat()
    m = MissionRun(session, "Write a thank-you note to my team", SEATS, mission="write", chat=chat,
                   prices=PRICES, moderator_model="fake/mod", budget_usd=5, on_checkpoint=on_checkpoint)
    holder["m"] = m
    asyncio.run(m.run_mission())
    after = chat.prompts[[i for i, p in enumerate(chat.prompts) if "STEP: SPLIT" in p[2]][0]:]
    assert after and all("Keep it under 100 words" in u for _, _, u in after)
    evs = events(session, m.run_id)
    assert any(t == "message_routed" and p["from"] == "client" and p["to"] == "all" for t, p in evs)


def test_failed_owner_hands_part_to_another_seat(session):
    chat = ScriptChat(fail={"fake/b"})
    m, res, _ = run_mission(session, "Plan meals for a week on a budget", mission="plan", chat=chat)
    assert res.status == "done" and res.absent == ["B"]
    assert all(p.owner != "B" and p.text for p in m.parts)


def test_scoring_prompt_hides_authors_even_from_the_transcript_dump(session):
    m, _, chat = run_mission(session, "Learn how compound interest works", mission="learn")
    for _, _, user in chat.steps("SCORE"):
        assert "[m" not in user  # no transcript lines at all


# ------------------------------------------------------------------ API


@pytest.fixture
def client(env, monkeypatch):
    from app import runs
    from app.config import get_settings
    from app.orchestrator import seats as seats_mod

    monkeypatch.setattr(openrouter, "chat", ScriptChat())
    monkeypatch.setattr(runs, "_prices", PRICES)
    monkeypatch.setattr(runs, "_prices_at", time.monotonic())
    monkeypatch.setattr(seats_mod, "load_seats", lambda path=None: SEATS)
    from app.main import app

    with TestClient(app) as c:
        login(c)
        monkeypatch.setattr(get_settings(), "moderator_model", "fake/mod")
        yield c


def _wait_for(ws, pred, seen):
    while True:
        msg = ws.receive_json()
        seen.append(msg)
        if pred(msg):
            return msg


def test_api_checkpoints_messages_and_download(client):
    assert {m["key"] for m in client.get("/api/missions").json()} >= {"ask", "write", "launch"}
    bad = client.post("/api/runs", json={"goal": "Make a logo", "seats": ["A", "B"], "budget_usd": 1,
                                         "mission": "nope"})
    assert bad.status_code == 422
    run_id = client.post("/api/runs", json={"goal": "Write a birthday message for my dad", "seats": ["A", "B", "C"],
                                            "budget_usd": 1, "mission": "write"}).json()["run_id"]
    seen = []
    with client.websocket_connect(f"/api/runs/{run_id}/ws") as ws:
        pick = _wait_for(ws, lambda m: m["type"] == "checkpoint_opened" and m["payload"]["kind"] == "pick", seen)
        r = client.post(f"/api/runs/{run_id}/checkpoint", json={"action": "pick", "option": "nope"})
        assert r.status_code == 422
        assert client.post(f"/api/runs/{run_id}/message", json={"text": "Mention his garden"}).status_code == 200
        option = pick["payload"]["options"][0]["id"]
        assert client.post(f"/api/runs/{run_id}/checkpoint",
                           json={"action": "pick", "option": option}).status_code == 200
        _wait_for(ws, lambda m: m["type"] == "checkpoint_opened" and m["payload"]["kind"] == "review", seen)
        assert client.post(f"/api/runs/{run_id}/checkpoint", json={"action": "changes"}).status_code == 422
        assert client.post(f"/api/runs/{run_id}/checkpoint", json={"action": "accept"}).status_code == 200
        _wait_for(ws, lambda m: m["type"] == "phase_changed" and m["payload"].get("status") == "done", seen)
    assert any(m["type"] == "message_done" and m["payload"].get("seat") == "client" for m in seen)
    file = client.get(f"/api/runs/{run_id}/files/deliverable.md")
    assert file.status_code == 200 and "attachment" in file.headers["content-disposition"]
    assert client.get(f"/api/runs/{run_id}/files/../../etc/passwd").status_code in (400, 404)
    assert client.post(f"/api/runs/{run_id}/checkpoint", json={"action": "accept"}).status_code == 409


def test_api_stop_while_waiting_at_checkpoint(client):
    run_id = client.post("/api/runs", json={"goal": "Plan a picnic", "seats": ["A", "B"], "budget_usd": 1,
                                            "mission": "plan"}).json()["run_id"]
    with client.websocket_connect(f"/api/runs/{run_id}/ws") as ws:
        _wait_for(ws, lambda m: m["type"] == "checkpoint_opened", [])
        assert client.post(f"/api/runs/{run_id}/control", json={"action": "stop"}).status_code == 200
        _wait_for(ws, lambda m: m["type"] == "phase_changed" and m["payload"].get("status") == "stopped", [])
    assert json.loads(json.dumps(client.get(f"/api/runs/{run_id}").json()))["status"] == "stopped"


def test_decide_debates_recommendations_not_nominations(session):
    m, res, _ = run_mission(session, "Should I buy a Kindle or a Kobo?", mission="decide")
    assert res.status == "done"
    assert m.compare["options"] == ["Kindle", "Kobo"]
    # Whatever was decided must be a recommendation from the debate phase, never a nomination.
    if m.decision:
        assert m.decision.phase == "debate" and isinstance(m.decision.round, int)
        assert m.decision.proposal.get("title")
    assert not any("None" in e.content for e in m.entries if e.seat == "moderator")


def test_decide_verdict_is_told_the_councils_decision(session):
    m, res, chat = run_mission(session, "Should I buy a Kindle or a Kobo?", mission="decide")
    verdicts = chat.steps("VERDICT")
    assert m.decision and verdicts
    assert f"The council's decision: {m.decision.proposal['title']}" in verdicts[-1][2]
    assert m.decision.proposal["title"] in m.deliverable
