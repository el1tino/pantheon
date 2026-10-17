import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import get_settings
from app.db import Message, Run
from app.db.session import get_engine
from app.gateway import openrouter


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app.db.session as db_session

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    monkeypatch.setattr(db_session, "_engine", None)
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_health_never_exposes_key(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-secret")
    get_settings.cache_clear()
    body = client.get("/api/health").json()
    assert body["openrouter_key_set"] is True
    assert "sk-secret" not in str(body)


def test_test_call_saves_run_and_message(client, monkeypatch):
    async def fake_chat(messages, model=None, max_tokens=None):
        return openrouter.ChatResult("fake/model", "Hello, council.", 10, 5, 0.0001)

    monkeypatch.setattr(openrouter, "chat", fake_chat)
    resp = client.post("/api/test-call", json={"prompt": "Say hi"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "Hello, council."
    assert data["tokens"] == 15

    with Session(get_engine()) as s:
        run = s.get(Run, data["run_id"])
        assert run.spent_usd == pytest.approx(0.0001)
        msgs = s.exec(select(Message).where(Message.run_id == run.id)).all()
        assert [m.content for m in msgs] == ["Hello, council."]


def test_test_call_reports_gateway_error(client, monkeypatch):
    async def failing_chat(*a, **k):
        raise openrouter.GatewayError("OPENROUTER_API_KEY is not set in .env")

    monkeypatch.setattr(openrouter, "chat", failing_chat)
    resp = client.post("/api/test-call", json={"prompt": "Say hi"})
    assert resp.status_code == 502
    assert "OPENROUTER_API_KEY" in resp.json()["detail"]
