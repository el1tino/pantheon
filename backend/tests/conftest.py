import pytest
from sqlmodel import Session

import app.db.session as db_session
from app.config import get_settings


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("DEMO_DIR", str(tmp_path / "demo"))  # not the recorded demo in the repo
    get_settings.cache_clear()
    monkeypatch.setattr(db_session, "_engine", None)
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def session(env):
    db_session.init_db()
    with Session(db_session.get_engine()) as s:
        yield s


def quick_check_site(site_dir):
    """In-process stand-in for the Docker check: links, a missing index and the logo.
    Tests marked `docker` use the real runner instead."""
    import re

    from app.orchestrator.execution import CheckResult

    errors, logo = [], None
    index = site_dir / "index.html"
    if not index.is_file():
        return CheckResult("failed", errors=[{"file": "site/index.html", "kind": "missing",
                                              "message": "site/index.html does not exist", "line": None}])
    for page in site_dir.rglob("*.html"):
        for ref in re.findall(r'\b(?:src|href)\s*=\s*["\']([^"\'#?]+)', page.read_text()):
            if re.match(r"^(https?:|mailto:|data:|//)", ref):
                continue
            exists = (page.parent / ref).is_file()
            if "logo" in ref.lower():
                logo = {"ref": ref, "exists": exists, "page": "site/index.html"}
            if not exists:
                errors.append({"file": f"site/{page.relative_to(site_dir)}", "kind": "missing",
                               "message": f"{ref} is referenced but does not exist", "line": None})
    for js in site_dir.rglob("*.js"):
        if "BROKEN" in js.read_text() or "initCarousel();" in js.read_text():
            errors.append({"file": f"site/{js.relative_to(site_dir)}", "kind": "runtime",
                           "message": "ReferenceError: BROKEN is not defined", "line": 1})
    return CheckResult("failed" if errors else "passed", errors=errors, logo=logo)


@pytest.fixture(autouse=True)
def _quick_checks(request, monkeypatch):
    if "docker" in request.keywords:
        return

    async def fake(site_dir):
        return quick_check_site(site_dir)

    monkeypatch.setattr("app.orchestrator.integration.check_site", fake)


def login(client, email="owner@example.com", password="correct horse battery", owner=True):
    """Create an account straight in the database and log the test client in."""
    from sqlmodel import Session, select

    from app import auth
    from app.db import User
    from app.db.session import get_engine

    with Session(get_engine()) as s:
        if not s.exec(select(User).where(User.email == email)).first():
            s.add(User(email=email, password_hash=auth.hash_password(password), is_owner=owner))
            s.commit()
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    from app import auth

    auth.reset_rate_limits()
