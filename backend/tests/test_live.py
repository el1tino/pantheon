"""Milestone 3: streaming tokens, pause/stop, file diffs, run API and the WebSocket."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.gateway import openrouter
from app.orchestrator.debate import Debate, RunControl
from app.orchestrator.streaming import ContentStreamer
from tests.test_debate import PRICES, SEATS, FakeChat, events, propose, reply


def _consensus_script(letter, kind, messages, n):
    if kind == "round1":
        return propose(f"Idea {letter}")
    if kind == "round2":
        return reply("agree", "m1", content='Agreed: "Idea A" wins.')
    return "**Decision**\n\nIdea A."


def test_content_streamer_handles_split_escapes():
    raw = '```json\n{"stance": "agree", "content": "Say \\"hi\\"\\nthen \\u00e9.", "x": 1}'
    s = ContentStreamer()
    out = "".join(s.feed(raw[i : i + 2]) for i in range(0, len(raw), 2))
    assert out == 'Say "hi"\nthen é.'


def test_token_events_spell_out_message_content(session):
    chat = FakeChat(_consensus_script)
    d = Debate(session, "goal", SEATS, chat=chat, prices=PRICES, moderator_model="fake/mod")
    asyncio.run(d.run_debate())
    evs = events(session, d.run_id)
    first_done = next(p for t, p in evs if t == "message_done")
    typed = "".join(p["text"] for t, p in evs if t == "token" and p["seat"] == "A")
    assert typed.startswith(first_done["content"])
    # The moderator's plain-text summary streams too.
    assert any(t == "token" and p["seat"] == "moderator" for t, p in evs)


def test_revised_proposal_counts_removed_lines(session):
    def script(letter, kind, messages, n):
        if kind == "round1":
            return propose(f"Idea {letter}")
        if kind == "round2" and letter == "A":
            return propose("Idea A, revised")
        if kind.startswith("round"):
            return reply("agree", "m5")
        return "summary"

    d = Debate(session, "goal", SEATS, chat=FakeChat(script), prices=PRICES,
               moderator_model="fake/mod")
    res = asyncio.run(d.run_debate())
    assert res.decision.id == "m5"
    diffs = [p for t, p in events(session, d.run_id) if t == "diff_applied"]
    a_files = [p for p in diffs if p["file"] == "proposals/A.md"]
    assert a_files[0]["lines_removed"] == 0 and a_files[0]["lines_added"] > 0
    assert a_files[1]["lines_removed"] > 0
    assert {"op": "+", "text": "# Idea A, revised"} in a_files[1]["lines"]
    assert any(p["file"] == "notes/B.md" for p in diffs)
    assert diffs[-1]["file"] == "decision.md" and diffs[-1]["seat"] == "moderator"


def test_stop_before_first_turn(session):
    control = RunControl()
    control.stop()
    chat = FakeChat(_consensus_script)
    d = Debate(session, "goal", SEATS, chat=chat, prices=PRICES, control=control)
    res = asyncio.run(d.run_debate())
    assert res.status == "stopped"
    assert sum(chat.calls.values()) == 0


def test_pause_waits_until_resumed(session):
    control = RunControl()
    control.pause()
    d = Debate(session, "goal", SEATS, chat=FakeChat(_consensus_script), prices=PRICES,
               moderator_model="fake/mod", control=control)

    async def main():
        task = asyncio.create_task(d.run_debate())
        await asyncio.sleep(0.05)
        assert not task.done()
        control.resume()
        return await task

    res = asyncio.run(main())
    assert res.status == "done"
    statuses = [p.get("status") for t, p in events(session, d.run_id) if t == "phase_changed"]
    assert "paused" in statuses and "running" in statuses


@pytest.fixture
def client(env, monkeypatch):
    from app import runs

    monkeypatch.setattr(openrouter, "chat", FakeChat(_consensus_script))
    monkeypatch.setattr(runs, "_prices", PRICES)
    monkeypatch.setattr(runs, "_prices_at", time.monotonic())
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_run_api_and_websocket_replay(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "moderator_model", "fake/mod")
    seats = client.get("/api/seats").json()
    assert len(seats) == 13 and "api_key" not in str(seats).lower()

    # Seat letters come from seats.yaml; route their model ids to the fake.
    from app.orchestrator import seats as seats_mod

    monkeypatch.setattr(seats_mod, "load_seats", lambda path=None: SEATS)
    resp = client.post("/api/runs", json={"goal": "Name a startup", "seats": ["A", "B", "C", "D"],
                                          "budget_usd": 1, "max_rounds": 3})
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]

    seen = []
    with client.websocket_connect(f"/api/runs/{run_id}/ws") as ws:
        # Read until both the history marker and the end of the run have arrived; the
        # fake gateway is fast, so the run may finish before or after we connect.
        while not (
            any(m["type"] == "caught_up" for m in seen)
            and any(m["payload"].get("status") == "done" for m in seen)
        ):
            seen.append(ws.receive_json())
    live_seqs = [m["seq"] for m in seen if m["type"] != "caught_up"]
    assert live_seqs == list(range(1, len(live_seqs) + 1))  # in order, no gaps, no repeats

    # A late joiner gets the whole run from storage, then the caught_up marker.
    with client.websocket_connect(f"/api/runs/{run_id}/ws") as ws:
        replay = []
        while True:
            msg = ws.receive_json()
            if msg["type"] == "caught_up":
                break
            replay.append(msg)
    assert [m["seq"] for m in replay] == list(range(1, len(replay) + 1))
    assert [m["seq"] for m in replay][-1] == live_seqs[-1]

    assert client.get(f"/api/runs/{run_id}").json()["status"] == "done"
    assert any(r["id"] == run_id for r in client.get("/api/runs").json())
    assert client.post(f"/api/runs/{run_id}/control", json={"action": "stop"}).status_code == 409


def test_websocket_rejects_other_origins(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
        "/api/runs/x/ws", headers={"origin": "https://evil.example"}
    ) as ws:
        ws.receive_json()


def test_websocket_streams_live_events(client, monkeypatch):
    from app.config import get_settings
    from app.orchestrator import seats as seats_mod

    monkeypatch.setattr(get_settings(), "moderator_model", "fake/mod")
    monkeypatch.setattr(seats_mod, "load_seats", lambda path=None: SEATS)
    monkeypatch.setattr(openrouter, "chat", FakeChat(_consensus_script, delay=0.05))
    run_id = client.post("/api/runs", json={"goal": "Slow run", "seats": ["A", "B"],
                                            "budget_usd": 1}).json()["run_id"]
    with client.websocket_connect(f"/api/runs/{run_id}/ws") as ws:
        seen = []
        while not any(m["payload"].get("status") == "done" for m in seen):
            seen.append(ws.receive_json())
    types = [m["type"] for m in seen]
    caught_up = types.index("caught_up")
    assert "message_done" in types[caught_up:]  # messages arrived live, after the history
    seqs = [m["seq"] for m in seen if m["type"] != "caught_up"]
    assert seqs == list(range(1, len(seqs) + 1))
