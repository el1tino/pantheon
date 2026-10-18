"""Milestone 5: workstream votes, the task plan, parallel building, reviews and the site."""

import asyncio
import re
import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.db import Task
from app.devtools.council_script import reply
from app.gateway import openrouter
from app.gateway.openrouter import ChatResult
from app.orchestrator import sandbox
from app.orchestrator.budget import BudgetExceeded
from app.orchestrator.missions import MissionRun
from tests.test_debate import PRICES, SEATS, events
from tests.test_missions import ScriptChat, run_mission


def build(session, goal="Build a landing page for my bakery", mission="build", **kw):
    return run_mission(session, goal, mission=mission, **kw)


def read(run_id, path):
    return sandbox.safe_path(run_id, path).read_text()


def test_build_mission_produces_a_working_multi_file_site(session):
    m, res, chat = build(session)
    assert res.status == "done", res.summary
    html = read(m.run_id, "site/index.html")
    assert 'href="styles.css"' in html and 'src="script.js"' in html
    assert "{" in read(m.run_id, "site/styles.css") and "addEventListener" in read(m.run_id, "site/script.js")
    assert "Task plan" in read(m.run_id, "docs/plan.md")
    tasks = session.exec(select(Task).where(Task.run_id == m.run_id)).all()
    built = [t for t in tasks if t.reviewer_seat]  # the build plan (not the light "make" parts)
    assert len(built) == 4 and all(t.status == "done" for t in built)
    assert all(t.owner_seat != t.reviewer_seat for t in built)
    evs = events(session, m.run_id)
    created = {p["path"] for t, p in evs if t == "artifact_created" and p["kind"] == "file"}
    assert {"site/index.html", "site/styles.css", "site/script.js", "docs/copy.md"} <= created
    assert any(t == "diff_applied" and p["file"] == "site/index.html" and p["lines_added"] > 10 for t, p in evs)
    review = [p for t, p in evs if t == "checkpoint_opened" and p["kind"] == "review"]
    assert review and review[0]["preview"] == "site/index.html"


def test_workstream_leads_are_voted_and_nobody_votes_for_themselves(session):
    m, res, _ = build(session)
    assert all(w.lead in {"A", "B", "C", "D"} for w in m.workstreams)
    role_votes = [p for t, p in events(session, m.run_id) if t == "vote_cast" and p.get("kind") == "role"]
    assert role_votes and all(v["voter"] != v["target"] for v in role_votes)
    leads = [p for t, p in events(session, m.run_id) if t == "task_updated" and p.get("kind") == "workstream"]
    assert len(leads) == len(m.workstreams)


def test_plan_checkpoint_applies_swaps_and_ignores_self_review(session):
    seen = {}

    async def on_checkpoint(kind, payload):
        if kind == "plan":
            seen["plan"] = payload
            t1, t2 = payload["tasks"][0], payload["tasks"][1]
            new_owner = next(s for s in payload["seats"] if s not in (t1["owner"], t1["reviewer"]))
            return {"action": "approve", "assignments": {
                t1["id"]: {"owner": new_owner},
                t2["id"]: {"owner": t2["owner"], "reviewer": t2["owner"]},  # invalid: ignored
            }}
        if kind == "pick":
            return {"action": "pick", "option": payload["options"][0]["id"]}
        return {"action": "accept"}

    m, res, _ = build(session, on_checkpoint=on_checkpoint)
    plan = seen["plan"]
    t1 = next(t for t in m.build_tasks if t.id == plan["tasks"][0]["id"])
    t2 = next(t for t in m.build_tasks if t.id == plan["tasks"][1]["id"])
    assert t1.owner not in (plan["tasks"][0]["owner"],) and t1.owner != t1.reviewer
    assert t2.reviewer == plan["tasks"][1]["reviewer"] != t2.owner


class TieChat(ScriptChat):
    """Everyone nominates for everything and votes for the next seat, so every vote ties."""

    async def __call__(self, messages, model=None, max_tokens=None, timeout=None, on_delta=None):
        user = next(m["content"] for m in messages if m["role"] == "user")
        system = messages[0]["content"]
        if "STEP: NOMINATE" in user and "workstreams" in user:
            ids = re.findall(r"^- (w\d+):", user, re.M)
            text = ('{"stance": "propose", "content": "I can lead any of these.", '
                    f'"proposal": {{"parts": {ids!r}, "pitch": "Versatile."}}}}').replace("'", '"')
        elif "STEP: ROLE VOTE" in user:
            me = re.search(r"seat ([A-M]) on the", system).group(1)
            votes = []
            for pid, cands in re.findall(r"^- ([pw]\d+) \([^)]*\): ([A-M](?:, [A-M])*)", user, re.M):
                options = cands.split(", ")
                votes.append({"part": pid, "target": options[("ABCD".index(me)) % len(options)]})
            import json
            text = json.dumps({"stance": "vote", "content": "Rotating votes.", "votes": votes})
        else:
            return await super().__call__(messages, model, max_tokens, timeout, on_delta)
        self.prompts.append((model, system, user))
        return ChatResult(model, text, 100, 50, 0.0001)


def test_tied_role_votes_go_to_the_moderator(session):
    m, res, chat = build(session, chat=TieChat())
    assert res.status == "done"
    tiebreaks = chat.steps("TIEBREAK")
    assert tiebreaks
    assert any(e.seat == "moderator" and "broken by the moderator" in e.content for e in m.entries)


class TimedChat(ScriptChat):
    def __init__(self, delay=0.05, **kw):
        super().__init__(**kw)
        self.delay = delay
        self.spans: dict[str, list[float]] = {}

    async def __call__(self, messages, model=None, max_tokens=None, timeout=None, on_delta=None):
        user = next(m["content"] for m in messages if m["role"] == "user")
        tag = re.search(r"STEP: (BUILD TASK t\d+)", user)
        start = time.monotonic()
        await asyncio.sleep(self.delay)
        out = await super().__call__(messages, model, max_tokens, timeout, on_delta)
        if tag:
            self.spans.setdefault(tag.group(1), [start, time.monotonic()])
        return out


def test_build_waves_respect_dependencies_and_run_in_parallel(session):
    chat = TimedChat()
    m, res, _ = build(session, chat=chat)
    assert res.status == "done"
    s = chat.spans
    # t2 depends on t1; t3 and t4 depend on t2 and run side by side.
    assert s["BUILD TASK t2"][0] >= s["BUILD TASK t1"][1]
    assert s["BUILD TASK t3"][0] >= s["BUILD TASK t2"][1] and s["BUILD TASK t4"][0] >= s["BUILD TASK t2"][1]
    assert s["BUILD TASK t3"][0] < s["BUILD TASK t4"][1] and s["BUILD TASK t4"][0] < s["BUILD TASK t3"][1]


def test_parallel_calls_cannot_jointly_overshoot_the_budget(session):
    paused = []

    async def decline(budget, exc):
        paused.append((exc.spent, exc.estimate, exc.cap))
        return None

    m = MissionRun(session, "goal", SEATS, chat=TimedChat(delay=0.1), prices={"fake/a": (0.0, 1e-5)},
                   budget_usd=0.025, on_budget_pause=decline, moderator_model="fake/mod")
    msgs = [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]

    async def main():
        return await asyncio.gather(*(m._call("A", "fake/a", msgs, max_tokens=1000) for _ in range(3)),
                                    return_exceptions=True)

    results = asyncio.run(main())
    # Each call is estimated at $0.01: two fit under $0.025, the third has to ask first.
    assert len(paused) == 1 and paused[0][0] == pytest.approx(0.02)
    assert sum(1 for r in results if isinstance(r, str)) == 2
    assert not any(isinstance(r, BudgetExceeded) for r in results)


class QuestionChat(ScriptChat):
    """t2's builder asks C a question before building."""

    async def __call__(self, messages, model=None, max_tokens=None, timeout=None, on_delta=None):
        user = next(m["content"] for m in messages if m["role"] == "user")
        if "STEP: BUILD TASK t2" in user and "You can ask once." in user:
            self.prompts.append((model, messages[0]["content"], user))
            text = ('{"stance": "question", "content": "Quick check first.", '
                    '"proposal": {"to": "C", "question": "Should the waitlist come before the features?"}}')
            return ChatResult(model, text, 100, 50, 0.0001)
        return await super().__call__(messages, model, max_tokens, timeout, on_delta)


def test_builder_question_is_routed_answered_and_used(session):
    m, res, chat = build(session, chat=QuestionChat())
    assert res.status == "done"
    t2 = next(t for t in m.build_tasks if t.id == "t2")
    assert t2.asked and t2.question["text"].startswith("Should the waitlist")
    to = t2.question["to"]
    assert to != t2.owner
    answers = chat.steps("ANSWER")
    assert answers and f"seat {to} on the" in answers[0][1]
    rebuilt = [u for _, _, u in chat.steps("BUILD TASK t2") if "ANSWER to your question" in u]
    assert rebuilt and "You can ask once." not in rebuilt[0]
    assert any(t == "task_updated" and p.get("question") for t, p in events(session, m.run_id))


class HarshReviewer(ScriptChat):
    async def __call__(self, messages, model=None, max_tokens=None, timeout=None, on_delta=None):
        user = next(m["content"] for m in messages if m["role"] == "user")
        if "STEP: REVIEW TASK" in user:
            self.prompts.append((model, messages[0]["content"], user))
            return ChatResult(model, '{"stance": "challenge", "content": "Still not right: redo the header."}',
                              100, 50, 0.0001)
        return await super().__call__(messages, model, max_tokens, timeout, on_delta)


def test_review_rounds_are_capped(session):
    m, res, chat = build(session, chat=HarshReviewer())
    assert res.status == "done"
    for t in m.build_tasks:
        assert len(chat.steps(f"REVIEW TASK {t.id}")) == 2
        review_fixes = [u for _, _, u in chat.steps(f"REVISE TASK {t.id}") if "redo the header" in u]
        assert len(review_fixes) == 2
    removed = [p for t, p in events(session, m.run_id) if t == "diff_applied" and p["lines_removed"] > 0]
    assert removed  # revisions really changed files


def test_failed_builder_hands_tasks_to_others(session):
    m, res, _ = build(session, chat=ScriptChat(fail={"fake/b"}))
    assert res.status == "done" and "B" in res.absent
    assert all(t.owner != "B" and t.status == "done" for t in m.build_tasks)
    assert sandbox.safe_path(m.run_id, "site/index.html").is_file()


def test_client_changes_after_review_go_to_the_right_tasks(session):
    reviews = []

    async def on_checkpoint(kind, payload):
        if kind == "pick":
            return {"action": "pick", "option": payload["options"][0]["id"]}
        if kind == "plan":
            return {"action": "approve"}
        reviews.append(payload)
        return {"action": "changes", "note": "Make the button orange"} if len(reviews) == 1 else {"action": "accept"}

    m, res, chat = build(session, on_checkpoint=on_checkpoint)
    assert len(reviews) == 2
    assert chat.steps("ROUTE CHANGES")
    revised = [u for _, _, u in chat.prompts if "STEP: REVISE TASK" in u and "Make the button orange" in u]
    assert revised


def test_launch_builds_site_and_business_documents(session):
    m, res, _ = build(session, goal="Come up with a business idea we could launch in a month", mission="launch")
    assert res.status == "done", res.summary
    for path in ["site/index.html", "docs/business-plan.md", "docs/pitch-deck.md", "docs/marketing-copy.md"]:
        assert sandbox.safe_path(m.run_id, path).is_file(), path
    assert any(p.title for p in m.parts)  # research notes were written first


def test_scripted_reply_writes_files_the_parser_accepts():
    from app.orchestrator.files import parse_build_reply

    user = ('GOAL: g\n\nCONTEXT:\nChosen direction: Bakery: Bread.\n\nSTEP: BUILD TASK t1. Task t1 "x": y. '
            "Write: site/index.html, site/styles.css.\nJSON: ...")
    r, files = parse_build_reply(reply("You are A, seat A on the x council", user))
    assert [f.path for f in files] == ["site/index.html", "site/styles.css"]


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
        monkeypatch.setattr(get_settings(), "moderator_model", "fake/mod")
        yield c


def _until(ws, pred):
    while True:
        msg = ws.receive_json()
        if pred(msg):
            return msg


def test_api_plan_checkpoint_site_and_tree(client):
    run_id = client.post("/api/runs", json={"goal": "Build a page for my dog-walking business",
                                            "seats": ["A", "B", "C", "D"], "budget_usd": 2,
                                            "mission": "build"}).json()["run_id"]
    with client.websocket_connect(f"/api/runs/{run_id}/ws") as ws:
        pick = _until(ws, lambda m: m["type"] == "checkpoint_opened" and m["payload"]["kind"] == "pick")
        client.post(f"/api/runs/{run_id}/checkpoint",
                    json={"action": "pick", "option": pick["payload"]["options"][0]["id"]})
        plan = _until(ws, lambda m: m["type"] == "checkpoint_opened" and m["payload"]["kind"] == "plan")["payload"]
        t1 = plan["tasks"][0]
        bad = client.post(f"/api/runs/{run_id}/checkpoint", json={
            "action": "approve", "assignments": {t1["id"]: {"owner": t1["reviewer"]}}})
        assert bad.status_code == 422 and "different seat" in bad.json()["detail"]
        assert client.post(f"/api/runs/{run_id}/checkpoint", json={
            "action": "approve", "assignments": {"t99": {"owner": "A"}}}).status_code == 422
        assert client.post(f"/api/runs/{run_id}/checkpoint", json={
            "action": "approve", "assignments": {t1["id"]: {"owner": "Z"}}}).status_code == 422
        assert client.post(f"/api/runs/{run_id}/checkpoint", json={"action": "approve"}).status_code == 200
        _until(ws, lambda m: m["type"] == "checkpoint_opened" and m["payload"]["kind"] == "review")
        client.post(f"/api/runs/{run_id}/checkpoint", json={"action": "accept"})
        _until(ws, lambda m: m["type"] == "phase_changed" and m["payload"].get("status") == "done")

    page = client.get(f"/api/runs/{run_id}/site/index.html")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    csp = page.headers["content-security-policy"]
    assert "connect-src 'none'" in csp and "frame-ancestors" in csp and "default-src 'none'" in csp
    assert client.get(f"/api/runs/{run_id}/site/").status_code == 200  # defaults to index.html
    assert client.get(f"/api/runs/{run_id}/site/styles.css").headers["content-type"].startswith("text/css")
    assert client.get(f"/api/runs/{run_id}/site/..%2F..%2F..%2Fetc%2Fpasswd").status_code in (400, 404)
    assert client.get(f"/api/runs/{run_id}/site/../goal.md").status_code in (400, 404)
    tree = {f["path"] for f in client.get(f"/api/runs/{run_id}/tree").json()}
    assert {"site/index.html", "site/styles.css", "site/script.js", "docs/plan.md"} <= tree
    inline = client.get(f"/api/runs/{run_id}/files/site/script.js?inline=true")
    assert "content-disposition" not in inline.headers and "addEventListener" in inline.text


def test_site_route_never_serves_files_outside_site(client):
    run_id = client.post("/api/runs", json={"goal": "Build a page", "seats": ["A", "B"], "budget_usd": 2,
                                            "mission": "build"}).json()["run_id"]
    with client.websocket_connect(f"/api/runs/{run_id}/ws") as ws:
        _until(ws, lambda m: m["type"] == "checkpoint_opened")
    # goal.md exists in the run folder, outside site/. Encoded dot-dots must not reach it.
    for raw in ["..%2Fgoal.md", "%2e%2e/goal.md", "%2e%2e%2fgoal.md"]:
        assert client.get(f"/api/runs/{run_id}/site/{raw}").status_code in (400, 404), raw
