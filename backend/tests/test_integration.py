"""Milestone 6: image consultants, Docker checks, the error loop, consistency, fact-checking
and the Create mission."""

import asyncio
import base64
import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from sqlmodel import select

from app.config import get_settings
from app.db import Task
from app.gateway import images
from app.orchestrator import sandbox
from app.orchestrator.execution import check_site, docker_args
from app.orchestrator.missions import MissionRun
from tests.test_debate import PRICES, SEATS, events
from tests.test_missions import ScriptChat, run_mission

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


# ------------------------------------------------------------------ image consultants


def mock_http(monkeypatch, handler):
    real = httpx.AsyncClient
    seen = []

    def factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return real(*args, transport=httpx.MockTransport(lambda r: (seen.append(r), handler(r))[1]), **kwargs)

    monkeypatch.setattr(images.httpx, "AsyncClient", factory)
    return seen


def test_openai_adapter_sends_key_only_to_openai(env, monkeypatch):
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-img-secret")
    seen = mock_http(monkeypatch, lambda r: httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}]}))
    result = asyncio.run(images.generate(images.CONSULTANTS["openai"], "a red fox", "image"))
    assert result.ext == ".png" and result.data == PNG and result.cost_usd == pytest.approx(0.07)
    req = seen[0]
    assert req.url.host == "api.openai.com" and req.headers["authorization"] == "Bearer sk-img-secret"
    assert json.loads(req.content)["prompt"] == "a red fox"


def test_recraft_adapter_downloads_and_sanitises_svg(env, monkeypatch):
    monkeypatch.setattr(get_settings(), "recraft_api_key", "rk-secret")
    evil = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>x()</script><rect width="9"/></svg>'

    def handler(r):
        if r.url.host == "external.api.recraft.ai":
            return httpx.Response(200, json={"data": [{"url": "https://img.recraft.ai/x.svg"}]})
        return httpx.Response(200, content=evil)

    seen = mock_http(monkeypatch, handler)
    result = asyncio.run(images.generate(images.CONSULTANTS["recraft"], "logo", "logo"))
    assert result.ext == ".svg" and b"script" not in result.data and b"onload" not in result.data
    assert b"<rect" in result.data
    assert "authorization" not in seen[1].headers  # the key is not sent to the download host


def test_gemini_adapter_reads_inline_image(env, monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "g-secret")
    body = {"candidates": [{"content": {"parts": [{"inlineData": {"data": base64.b64encode(PNG).decode()}}]}}]}
    seen = mock_http(monkeypatch, lambda r: httpx.Response(200, json=body))
    assert asyncio.run(images.generate(images.CONSULTANTS["gemini"], "x", "image")).ext == ".png"
    assert seen[0].headers["x-goog-api-key"] == "g-secret"


def test_provider_errors_and_bad_images_are_rejected(env, monkeypatch):
    monkeypatch.setattr(get_settings(), "openai_api_key", "k")
    mock_http(monkeypatch, lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(images.ImageError, match="HTTP 500"):
        asyncio.run(images.generate(images.CONSULTANTS["openai"], "x", "image"))
    with pytest.raises(images.ImageError):
        images.check_image(b"MZ\x90\x00 not an image")
    with pytest.raises(images.ImageError, match="larger"):
        images.check_image(PNG + b"\x00" * images.MAX_IMAGE_BYTES)


def test_consultant_choice_falls_back_sensibly(env, monkeypatch):
    assert images.pick_consultant("openai", "logo").key == "practice"  # no keys at all
    monkeypatch.setattr(get_settings(), "recraft_api_key", "r")
    monkeypatch.setattr(get_settings(), "openai_api_key", "o")
    assert images.pick_consultant(None, "logo").key == "recraft"
    assert images.pick_consultant("openai", "logo").key == "openai"  # the design lead's choice wins
    assert images.pick_consultant("nonsense", "image").key == "openai"


def test_image_keys_never_reach_a_model(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-img-secret-123")
    monkeypatch.setattr(get_settings(), "recraft_api_key", "rk-secret-456")
    mock_http(monkeypatch, lambda r: httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})
              if r.url.host == "api.openai.com" else httpx.Response(200, json={"data": [{"url": "https://cdn/x"}]})
              if r.url.host == "external.api.recraft.ai" else httpx.Response(200, content=PNG))
    m, res, chat = run_mission(session, "Build a landing page for my bakery", mission="build")
    assert res.status == "done" and m.images
    for _, system, user in chat.prompts:
        assert "secret" not in system and "secret" not in user


# ------------------------------------------------------------------ Docker checks


def test_docker_args_lock_the_container_down(tmp_path):
    args = docker_args(tmp_path, "pantheon-runner:1", "c1")
    joined = " ".join(args)
    for flag in ["--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges",
                 "--user 1000:1000", "--pids-limit 64", "--env-file /dev/null"]:
        assert flag in joined, flag
    mount = args[args.index("-v") + 1]
    assert mount.endswith(":/work/site:ro") and mount.startswith(str(tmp_path.resolve()))
    assert "-e" not in args  # no environment variables, so no secrets


def test_check_reports_not_run_without_docker(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html></html>")
    monkeypatch.setattr("app.orchestrator.execution.shutil.which", lambda name: None)
    result = asyncio.run(check_site(tmp_path))
    assert result.status == "not_run" and "docker build" in result.detail


def _runner_ready() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "image", "inspect", get_settings().runner_image],
                              capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


needs_docker = pytest.mark.skipif(not _runner_ready(), reason="Docker or the runner image is not available")


def _site(tmp_path: Path, script: str, logo: bool = True) -> Path:
    site = tmp_path / "site"
    site.mkdir()
    header = '<img src="logo.svg" alt="">' if logo else ""
    (site / "index.html").write_text(
        f'<!doctype html><html><head><link rel="stylesheet" href="styles.css"><script src="script.js" defer>'
        f'</script></head><body><header>{header}</header><p id="x"></p></body></html>')
    (site / "styles.css").write_text("body { color: red; }")
    (site / "script.js").write_text(script)
    if logo:
        (site / "logo.svg").write_bytes(images.practice_svg("logo", "logo"))
    return site


@pytest.mark.docker
@needs_docker
def test_real_docker_check_passes_a_good_site(env, tmp_path):
    result = asyncio.run(check_site(_site(tmp_path, 'document.getElementById("x").textContent = "hi";')))
    assert result.status == "passed", result.errors
    assert result.logo and result.logo["exists"]


@pytest.mark.docker
@needs_docker
def test_real_docker_check_catches_runtime_and_syntax_errors(env, tmp_path):
    result = asyncio.run(check_site(_site(tmp_path, "document.getElementById('nope').textContent = 1;")))
    assert result.status == "failed"
    assert any(e["kind"] == "runtime" and e["file"] == "site/script.js" for e in result.errors)
    (tmp_path / "site" / "script.js").write_text("function (")
    result = asyncio.run(check_site(tmp_path / "site"))
    assert any(e["kind"] == "syntax" for e in result.errors)


@pytest.mark.docker
@needs_docker
def test_real_docker_check_has_no_network(env, tmp_path):
    script = ('fetch("http://example.com").then(() => console.error("NETWORK REACHED"))'
              '.catch(() => {});')
    result = asyncio.run(check_site(_site(tmp_path, script)))
    assert not any("NETWORK REACHED" in e["message"] for e in result.errors)


# ------------------------------------------------------------------ the Integrate phase


def test_error_loop_sends_failures_to_the_owner_and_rechecks(session):
    m, res, chat = run_mission(session, "Build a landing page for my bakery, Crumb and Co", mission="build")
    assert res.status == "done"
    assert [c["status"] for c in m.checks] == ["failed", "passed"]
    assert sandbox.safe_path(m.run_id, "logs/check-1.json").is_file()
    fixes = [u for _, _, u in chat.steps("REVISE TASK") if "failed" in u and "initCarousel" in u]
    script_owner = next(t for t in m.build_tasks if "site/script.js" in t.files)
    assert fixes and all(f"REVISE TASK {script_owner.id}" in u for u in fixes)
    fix_msg = next(e for e in m.entries if e.content.startswith("Fixed the errors from the check"))
    assert fix_msg.unverified  # claims "it works now" without evidence
    checks = [p for t, p in events(session, m.run_id) if t == "artifact_created" and p["kind"] == "check"]
    assert [c["status"] for c in checks] == ["failed", "passed"]


class NoLogoChat(ScriptChat):
    """Builders that never ask for a logo on their first pass."""

    async def __call__(self, messages, model=None, max_tokens=None, timeout=None, on_delta=None):
        out = await super().__call__(messages, model, max_tokens, timeout, on_delta)
        user = next(m["content"] for m in messages if m["role"] == "user")
        if "STEP: BUILD TASK" in user:
            head, sep, tail = out.content.partition("=== FILE:")
            data = json.loads(head)
            data["proposal"] = None
            out.content = json.dumps(data) + "\n" + sep + tail.replace('<img src="logo.svg" alt="" class="logo">', "")
        return out


def test_integrate_makes_sure_the_site_uses_its_own_logo(session):
    m, res, chat = run_mission(session, "Build a page for my yoga studio", mission="build", chat=NoLogoChat())
    assert res.status == "done"
    assert any(i["kind"] == "logo" for i in m.images)
    assert 'src="logo.svg"' in sandbox.safe_path(m.run_id, "site/index.html").read_text()
    assert m.checks[-1]["status"] == "passed"


def test_consistency_pass_routes_mismatches_to_file_owners(session):
    m, res, chat = run_mission(session, "Come up with a business idea we could launch in a month", mission="launch")
    assert res.status == "done"
    owner = next(t for t in m.build_tasks if "docs/pitch-deck.md" in t.files)
    fixes = [u for _, _, u in chat.steps(f"REVISE TASK {owner.id}") if "Consistency pass" in u]
    assert fixes and "different product name" in fixes[0]


def test_claims_need_evidence(session):
    m = MissionRun(session, "goal", SEATS, chat=ScriptChat(), prices=PRICES)
    sandbox.write_text(m.run_id, "logs/check-1.json", json.dumps({"status": "failed"}))
    sandbox.write_text(m.run_id, "logs/check-2.json", json.dumps({"status": "passed"}))
    from app.orchestrator.protocol import AgentReply

    def add(content, evidence=None):
        proposal = {"evidence": evidence} if evidence else None
        return m._add("A", "x", AgentReply(stance="report", content=content, proposal=proposal), record=False)

    assert not add("I wrote the header and footer.").unverified  # no claim, nothing to prove
    assert add("All tests pass.").unverified
    assert add("It works now.", ["logs/check-1.json"]).unverified  # that check failed
    assert add("It works now.", ["../../etc/passwd"]).unverified
    assert not add("It works now.", ["logs/check-2.json"]).unverified
    done = [p for t, p in events(session, m.run_id) if t == "message_done"]
    assert [d["unverified"] for d in done] == [False, True, True, True, False]


def test_image_requests_go_through_the_budget(session):
    paused = []

    async def decline(budget, exc):
        paused.append(exc.estimate)
        return None

    m = MissionRun(session, "goal", SEATS, chat=ScriptChat(), prices=PRICES, budget_usd=0.05,
                   on_budget_pause=decline)
    get_settings().image_prices["practice"] = 0.08  # pretend the practice image costs money
    try:
        from app.orchestrator.debate import RunStopped

        with pytest.raises(RunStopped):
            asyncio.run(m._commission("A", {"path": "site/logo.svg", "prompt": "p", "kind": "logo", "consultant": None}))
    finally:
        get_settings().image_prices["practice"] = 0.0
    assert paused == [pytest.approx(0.08)]
    assert not sandbox.safe_path(m.run_id, "site/logo.svg").exists()


# ------------------------------------------------------------------ Create


def test_create_mission_makes_reviewed_images_and_a_gallery(session):
    reviews = []

    async def on_checkpoint(kind, payload):
        if kind == "pick":
            return {"action": "pick", "option": payload["options"][0]["id"]}
        reviews.append(payload)
        return {"action": "accept"}

    m, res, chat = run_mission(session, "Make a logo and banner for my coffee cart", mission="create",
                               on_checkpoint=on_checkpoint)
    assert res.status == "done"
    assert len(m.images) == 3 and all(sandbox.safe_path(m.run_id, i["path"]).is_file() for i in m.images)
    assert all(t.owner and t.reviewer and t.owner != t.reviewer for t in m.build_tasks)
    rows = session.exec(select(Task).where(Task.run_id == m.run_id)).all()
    assert rows == [] or all(r.owner_seat != r.reviewer_seat for r in rows)
    assert len(chat.steps("IMAGE REVIEW")) == 3
    regenerated = [p for t, p in events(session, m.run_id) if t == "diff_applied" and p["lines_removed"] == 1]
    challenged = sum(1 for _, _, u in chat.steps("IMAGE PROMPT") if "Revise it:" in u)
    assert len(regenerated) == challenged
    assert reviews and len(reviews[0]["images"]) == 3


def test_create_changes_regenerate_the_routed_images(session):
    reviews = []

    async def on_checkpoint(kind, payload):
        if kind == "pick":
            return {"action": "pick", "option": payload["options"][0]["id"]}
        reviews.append(payload)
        return {"action": "changes", "note": "Warmer colours please"} if len(reviews) == 1 else {"action": "accept"}

    m, res, chat = run_mission(session, "Make a logo for my bike shop", mission="create", on_checkpoint=on_checkpoint)
    assert res.status == "done" and len(reviews) == 2
    assert [u for _, _, u in chat.steps("IMAGE PROMPT") if "Warmer colours please" in u]


def test_site_route_serves_images(env):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        m_id = "imgtest"
        from sqlmodel import Session

        from app.db import Run
        from app.db.session import get_engine

        with Session(get_engine()) as s:
            s.add(Run(id=m_id, goal="g"))
            s.commit()
        sandbox.write_bytes(m_id, "site/logo.png", PNG)
        sandbox.write_bytes(m_id, "site/logo.svg", images.practice_svg("x", "logo"))
        assert client.get(f"/api/runs/{m_id}/site/logo.png").headers["content-type"] == "image/png"
        svg = client.get(f"/api/runs/{m_id}/site/logo.svg")
        assert svg.headers["content-type"].startswith("image/svg+xml")
        assert "default-src 'none'" in svg.headers["content-security-policy"]


def test_unavailable_consultant_is_said_out_loud(session):
    m = MissionRun(session, "goal", SEATS, chat=ScriptChat(), prices=PRICES)
    path = asyncio.run(m._commission("A", {"path": "site/logo.svg", "prompt": "p", "kind": "logo",
                                           "consultant": "recraft"}))
    assert path == "site/logo.svg" and m.images[0]["consultant"] == "practice"
    assert any("Recraft (vector) isn't connected" in e.content for e in m.entries)
