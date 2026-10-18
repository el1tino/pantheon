"""Milestone 7: accounts, invites, sessions, run access and demo mode."""

import gzip
import json
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import auth
from app.config import get_settings
from app.db import LoginSession, Run, User
from app.db.session import get_engine
from app.gateway import openrouter
from tests.conftest import login
from tests.test_debate import PRICES, SEATS
from tests.test_missions import ScriptChat

RUN = {"goal": "Write a toast", "seats": ["A", "B"], "budget_usd": 1, "mission": "write"}


@pytest.fixture
def app_client(env, monkeypatch):
    from app import runs
    from app.orchestrator import seats as seats_mod

    monkeypatch.setattr(openrouter, "chat", ScriptChat())
    monkeypatch.setattr(runs, "_prices", PRICES)
    monkeypatch.setattr(runs, "_prices_at", time.monotonic())
    monkeypatch.setattr(seats_mod, "load_seats", lambda path=None: SEATS)
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_everything_private_needs_a_login(app_client):
    c = app_client
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/runs").status_code == 401
    assert c.post("/api/runs", json=RUN).status_code == 401
    assert c.post("/api/test-call", json={"prompt": "hi"}).status_code == 401
    assert c.get("/api/auth/me").status_code == 401
    assert c.post("/api/invites").status_code == 401


def test_login_sets_a_safe_cookie_and_logout_ends_it(app_client):
    c = app_client
    login(c)
    cookie = next(h for h in c.cookies.jar if h.name == auth.COOKIE)
    assert len(cookie.value) > 30
    raw = c.post("/api/auth/login", json={"email": "owner@example.com", "password": "correct horse battery"})
    header = raw.headers["set-cookie"].lower()
    assert "httponly" in header and "samesite=lax" in header and "path=/" in header
    with Session(get_engine()) as s:
        stored = s.exec(select(LoginSession)).all()
        assert stored and all(cookie.value not in r.token_hash for r in stored)  # only a hash is stored
    assert c.get("/api/auth/me").json()["email"] == "owner@example.com"
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").status_code == 401


def test_passwords_are_hashed_and_wrong_ones_rate_limited(app_client):
    c = app_client
    login(c)
    c.post("/api/auth/logout")
    with Session(get_engine()) as s:
        u = s.exec(select(User)).first()
        assert u.password_hash.startswith("$argon2") and "correct horse" not in u.password_hash
    for _ in range(auth.MAX_FAILS_PER_EMAIL):
        assert c.post("/api/auth/login", json={"email": "owner@example.com", "password": "nope"}).status_code == 401
    r = c.post("/api/auth/login", json={"email": "owner@example.com", "password": "correct horse battery"})
    assert r.status_code == 429  # locked for a while, even with the right password


def test_expired_sessions_are_refused(app_client):
    c = app_client
    login(c)
    with Session(get_engine()) as s:
        for row in s.exec(select(LoginSession)).all():
            row.expires_at = auth.now() - timedelta(minutes=1)
            s.add(row)
        s.commit()
    assert c.get("/api/auth/me").status_code == 401


def test_owner_comes_from_env_on_first_start(env, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_email", "Me@Example.com")
    monkeypatch.setattr(get_settings(), "admin_password", "a long enough password")
    from app.main import app

    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"email": "me@example.com", "password": "a long enough password"})
        assert r.status_code == 200 and r.json()["is_owner"] is True


def test_invites_are_single_use_and_only_from_the_owner(app_client):
    c = app_client
    login(c)
    invite = c.post("/api/invites").json()
    code = invite["code"]
    assert invite["path"] == f"/invite/{code}"
    c.post("/api/auth/logout")
    assert c.get(f"/api/invites/{code}").json() == {"valid": True}
    short = c.post(f"/api/invites/{code}/accept", json={"email": "friend@example.com", "password": "short"})
    assert short.status_code == 422
    ok = c.post(f"/api/invites/{code}/accept", json={"email": "Friend@Example.com", "password": "a good long password"})
    assert ok.status_code == 200 and ok.json() == {**ok.json(), "email": "friend@example.com", "is_owner": False}
    assert c.get("/api/auth/me").json()["email"] == "friend@example.com"  # logged straight in
    assert c.post("/api/invites").status_code == 403  # friends can't invite
    c.post("/api/auth/logout")
    again = c.post(f"/api/invites/{code}/accept", json={"email": "x@example.com", "password": "a good long password"})
    assert again.status_code == 404
    assert c.get(f"/api/invites/{code}").json() == {"valid": False}
    assert c.get("/api/invites/not-a-real-code").json() == {"valid": False}


def test_people_only_see_and_change_their_own_runs(app_client):
    c = app_client
    login(c)
    code = c.post("/api/invites").json()["code"]
    owner_run = c.post("/api/runs", json=RUN).json()["run_id"]
    c.post("/api/auth/logout")
    c.post(f"/api/invites/{code}/accept", json={"email": "friend@example.com", "password": "a good long password"})
    assert [r["id"] for r in c.get("/api/runs").json()] == []
    for path in ["", "/events", "/tree", "/files/goal.md"]:
        assert c.get(f"/api/runs/{owner_run}{path}").status_code == 404, path
    assert c.post(f"/api/runs/{owner_run}/control", json={"action": "stop"}).status_code == 404
    assert c.post(f"/api/runs/{owner_run}/message", json={"text": "hi"}).status_code == 404
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), c.websocket_connect(f"/api/runs/{owner_run}/ws") as ws:
        ws.receive_json()
    mine = c.post("/api/runs", json=RUN).json()["run_id"]
    assert [r["id"] for r in c.get("/api/runs").json()] == [mine]
    c.post("/api/auth/logout")
    with pytest.raises(WebSocketDisconnect), c.websocket_connect(f"/api/runs/{mine}/ws") as ws:
        ws.receive_json()


def test_writes_from_other_sites_are_refused(app_client):
    c = app_client
    login(c)
    r = c.post("/api/runs", json=RUN, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert c.post("/api/runs", json=RUN, headers={"origin": get_settings().frontend_origin}).status_code == 200


def test_public_runs_are_read_only_for_everyone(app_client):
    c = app_client
    with Session(get_engine()) as s:
        s.add(Run(id="demo-x", goal="A demo", status="done", phase="build", public=True))
        s.commit()
    assert c.get("/api/runs/demo-x").status_code == 200  # no login needed
    assert c.get("/api/runs/demo-x/events").json() == []
    assert [d["id"] for d in c.get("/api/demos").json()] == ["demo-x"]
    login(c)
    assert c.post("/api/runs/demo-x/message", json={"text": "hi"}).status_code == 403
    assert c.get("/api/runs/demo-x").json()["can_change"] is False
    assert "demo-x" not in [r["id"] for r in c.get("/api/runs").json()]


def test_demo_mode_refuses_new_runs(app_client, monkeypatch):
    c = app_client
    login(c)
    monkeypatch.setattr(get_settings(), "demo_mode", True)
    r = c.post("/api/runs", json=RUN)
    assert r.status_code == 403 and "demo" in r.json()["detail"]
    assert c.get("/api/config/public").json()["demo_mode"] is True


def test_a_run_exported_as_a_demo_imports_as_a_public_replay(app_client):
    from app import demo
    from app.db import Event
    from app.orchestrator import sandbox

    c = app_client
    with Session(get_engine()) as s:
        s.add(Run(id="r1", goal="Build a page", status="done", phase="integrate", spent_usd=0.02))
        for seq, type_ in enumerate(["phase_changed", "token", "message_done"], start=1):
            s.add(Event(run_id="r1", seq=seq, type=type_, payload_json=json.dumps({"n": seq})))
        s.commit()
        site = sandbox.safe_path("r1", "site/index.html")
        site.parent.mkdir(parents=True)
        site.write_text("<h1>Hi</h1>")
        folder = demo.export_demo(s, "r1", "page")
        assert (folder / "files/site/index.html").is_file()
        assert demo.import_demos(s) == ["demo-page"]
        assert demo.import_demos(s) == []  # unchanged, so not imported twice

    c.cookies.clear()  # anyone can watch it
    events = c.get("/api/runs/demo-page/events").json()
    assert [e["type"] for e in events] == ["phase_changed", "token", "message_done"]
    assert all(isinstance(e["at"], float) for e in events)
    info = c.get("/api/runs/demo-page").json()
    assert info["public"] is True and info["can_change"] is False
    assert c.get(f"/api/sites/{info['site_key']}/index.html").text == "<h1>Hi</h1>"
    assert "demo-page" in [d["id"] for d in c.get("/api/demos").json()]


def test_a_demo_never_replaces_a_real_run(app_client, env):
    from app import demo

    folder = env / "demo" / "x"
    folder.mkdir(parents=True)
    (folder / "run.json").write_text(json.dumps({"id": "r2", "goal": "Imported"}))
    with Session(get_engine()) as s:
        s.add(Run(id="r2", goal="Mine", status="done", phase="done"))
        s.commit()
        assert demo.import_demos(s) == []
        assert s.get(Run, "r2").goal == "Mine"


def test_a_changed_demo_is_imported_again(app_client):
    from app import demo
    from app.db import Event

    with Session(get_engine()) as s:
        s.add(Run(id="r3", goal="Demo", status="done", phase="done"))
        s.add(Event(run_id="r3", seq=1, type="phase_changed", payload_json=json.dumps({"seats": [{"letter": "A"}]})))
        s.commit()
        folder = demo.export_demo(s, "r3", "seats")
        assert demo.import_demos(s) == ["demo-seats"]
        # The recording gains seat logos: the next start replaces the imported copy.
        path = folder / "events.json.gz"
        with gzip.open(path, "rt") as f:
            events = json.load(f)
        events[0]["payload"]["seats"][0]["logo"] = "claude"
        with gzip.open(path, "wt") as f:
            json.dump(events, f)
        assert demo.import_demos(s) == ["demo-seats"]
        first = s.exec(select(Event).where(Event.run_id == "demo-seats", Event.seq == 1)).one()
        assert json.loads(first.payload_json)["seats"][0]["logo"] == "claude"
        assert demo.import_demos(s) == []
