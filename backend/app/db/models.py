"""The seven tables from the spec, plus users, invites and login sessions."""

import secrets
from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> str:
    return uuid4().hex[:12]


class Run(SQLModel, table=True):
    __tablename__ = "runs"
    id: str = Field(default_factory=_id, primary_key=True)
    goal: str
    status: str = "created"
    phase: str = "convene"
    budget_usd: float = 1.0
    spent_usd: float = 0.0
    created_at: datetime = Field(default_factory=_now)
    owner_id: str | None = Field(default=None, index=True)
    public: bool = False  # demo runs: readable by anyone, changeable by no one
    # Capability key in the site preview URL. The sandboxed preview has an opaque origin, so the
    # browser sends no login cookie with its requests; knowing this key is the permission.
    site_key: str = Field(default_factory=lambda: secrets.token_urlsafe(18), index=True)


class User(SQLModel, table=True):
    __tablename__ = "users"
    id: str = Field(default_factory=_id, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    is_owner: bool = False
    created_at: datetime = Field(default_factory=_now)


class Invite(SQLModel, table=True):
    __tablename__ = "invites"
    id: str = Field(default_factory=_id, primary_key=True)
    code_hash: str = Field(index=True, unique=True)  # the code itself is only ever shown once
    created_by: str
    created_at: datetime = Field(default_factory=_now)
    expires_at: datetime
    used_by: str | None = None
    used_at: datetime | None = None


class LoginSession(SQLModel, table=True):
    __tablename__ = "login_sessions"
    token_hash: str = Field(primary_key=True)
    user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=_now)
    expires_at: datetime


class Seat(SQLModel, table=True):
    __tablename__ = "seats"
    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="runs.id", index=True)
    letter: str
    name: str
    model_id: str
    colour: str
    # No seat has a fixed role. This holds the role the council votes it into (Roles phase).
    role: str = ""
    skills: str = ""


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    id: str = Field(default_factory=_id, primary_key=True)
    run_id: str = Field(foreign_key="runs.id", index=True)
    seat: str
    phase: str
    stance: str
    reply_to: str | None = None
    content: str
    tokens: int = 0
    cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=_now)


class Vote(SQLModel, table=True):
    __tablename__ = "votes"
    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="runs.id", index=True)
    phase: str
    voter_seat: str
    target: str
    score: int


class Task(SQLModel, table=True):
    __tablename__ = "tasks"
    id: str = Field(default_factory=_id, primary_key=True)
    run_id: str = Field(foreign_key="runs.id", index=True)
    title: str
    owner_seat: str | None = None
    reviewer_seat: str | None = None
    status: str = "todo"
    depends_on: str = ""  # comma-separated task ids


class Artifact(SQLModel, table=True):
    __tablename__ = "artifacts"
    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="runs.id", index=True)
    task_id: str | None = Field(default=None, foreign_key="tasks.id")
    path: str
    kind: str
    version: int = 1
    created_by: str
    lines_added: int = 0
    lines_removed: int = 0


class Event(SQLModel, table=True):
    __tablename__ = "events"
    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="runs.id", index=True)
    seq: int
    type: str
    payload_json: str
    at: datetime = Field(default_factory=_now)
