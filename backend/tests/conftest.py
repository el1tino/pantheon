import pytest
from sqlmodel import Session

import app.db.session as db_session
from app.config import get_settings


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    monkeypatch.setattr(db_session, "_engine", None)
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def session(env):
    db_session.init_db()
    with Session(db_session.get_engine()) as s:
        yield s
