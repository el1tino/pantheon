import asyncio
import json
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app import auth, demo, runs
from app.auth import current_user, optional_user, owner_user
from app.config import APP_NAME, get_settings
from app.db import Event, Message, Run, User, get_session, init_db
from app.db.session import get_engine
from app.events import bus
from app.gateway import openrouter
from app.orchestrator import sandbox
from app.orchestrator.missions import MISSIONS, public_missions
from app.orchestrator.seats import load_seats, pick_seats


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_settings().projects_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    with Session(get_engine()) as session:
        auth.bootstrap_owner(session)
        demo.import_demos(session)
    yield


app = FastAPI(title=APP_NAME, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    allow_credentials=True,
)


@app.middleware("http")
async def same_origin_writes(request: Request, call_next):
    """CSRF guard on top of SameSite cookies: a browser request that changes something must
    come from the app's own origin."""
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin != get_settings().frontend_origin:
        return JSONResponse({"detail": "Cross-site request refused."}, status_code=403)
    return await call_next(request)


@app.get("/api/health")
def health() -> dict:
    return {"app": APP_NAME, "status": "ok"}


@app.get("/api/config/public")
def public_config() -> dict:
    # Only non-secret values belong here; this is sent to the browser.
    return {"app_name": APP_NAME, "demo_mode": get_settings().demo_mode}


# --------------------------------------------------------------------------- accounts


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


def _user_dict(user: User) -> dict:
    return {"id": user.id, "email": user.email, "is_owner": user.is_owner}


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request, response: Response, session: Session = Depends(get_session)) -> dict:
    email = body.email.strip().lower()
    address = request.client.host if request.client else "?"
    auth.check_rate(address, email)
    user = session.exec(select(User).where(User.email == email)).first()
    if not user or not auth.verify_password(user.password_hash, body.password):
        auth.record_fail(address, email)
        raise HTTPException(status_code=401, detail="Wrong email or password.")
    auth.start_session(session, user, response)
    return _user_dict(user)


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, session: Session = Depends(get_session)) -> dict:
    auth.end_session(session, request.cookies.get(auth.COOKIE), response)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)) -> dict:
    return _user_dict(user)


@app.post("/api/invites")
def create_invite(owner: User = Depends(owner_user), session: Session = Depends(get_session)) -> dict:
    code, invite = auth.new_invite(session, owner)
    return {"code": code, "path": f"/invite/{code}", "expires_at": invite.expires_at.isoformat()}


@app.get("/api/invites/{code}")
def check_invite(code: str, session: Session = Depends(get_session)) -> dict:
    return {"valid": auth.find_invite(session, code) is not None}


@app.post("/api/invites/{code}/accept")
def accept_invite(code: str, body: LoginIn, response: Response, session: Session = Depends(get_session)) -> dict:
    invite = auth.find_invite(session, code)
    if not invite:
        raise HTTPException(status_code=404, detail="This invite is used, expired or wrong.")
    email = auth.normalise_email(body.email)
    auth.check_password_rules(body.password)
    if session.exec(select(User).where(User.email == email)).first():
        raise HTTPException(status_code=409, detail="That email already has an account.")
    user = User(email=email, password_hash=auth.hash_password(body.password))
    session.add(user)
    session.flush()
    invite.used_by, invite.used_at = user.id, auth.now()
    session.add(invite)
    session.commit()
    auth.start_session(session, user, response)
    return _user_dict(user)


class TestCallIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


class TestCallOut(BaseModel):
    run_id: str
    model: str
    reply: str
    tokens: int
    cost_usd: float | None


@app.post("/api/test-call", response_model=TestCallOut)
async def test_call(body: TestCallIn, user: User = Depends(current_user), session: Session = Depends(get_session)):
    settings = get_settings()
    try:
        result = await openrouter.chat(
            [
                {"role": "system", "content": f"You are a helpful member of the {APP_NAME} council. Be brief."},
                {"role": "user", "content": body.prompt},
            ],
            max_tokens=settings.test_call_max_tokens,
        )
    except openrouter.GatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    tokens = result.prompt_tokens + result.completion_tokens
    cost = result.cost_usd or 0.0
    run = Run(goal=body.prompt, status="done", phase="test", spent_usd=cost, owner_id=user.id)
    session.add(run)
    session.flush()
    session.add(
        Message(
            run_id=run.id, seat="test", phase="test", stance="report",
            content=result.content, tokens=tokens, cost_usd=cost,
        )
    )
    session.commit()
    return TestCallOut(
        run_id=run.id, model=result.model, reply=result.content,
        tokens=tokens, cost_usd=result.cost_usd,
    )


# --------------------------------------------------------------------------- runs


@app.get("/api/seats")
def list_seats() -> list[dict]:
    return [
        {"letter": s.letter, "name": s.name, "provider": s.provider, "colour": s.colour,
         "model_id": s.model_id}
        for s in load_seats()
    ]


class RunIn(BaseModel):
    goal: str = Field(min_length=3, max_length=4000)
    seats: list[str] = Field(min_length=1, max_length=13)
    budget_usd: float = Field(gt=0, le=50)
    max_rounds: int = Field(default=3, ge=1, le=6)
    cheap: bool = False  # every seat uses the cheap default model
    mission: str = "auto"


@app.get("/api/missions")
def list_missions() -> list[dict]:
    return public_missions()


@app.post("/api/runs")
async def create_run(body: RunIn, user: User = Depends(current_user)) -> dict:
    if get_settings().demo_mode:
        raise HTTPException(status_code=403, detail="This is a demo server: new runs are switched off.")
    try:
        seats = pick_seats([x.strip().upper() for x in body.seats])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.mission != "auto" and (body.mission not in MISSIONS or not MISSIONS[body.mission].available):
        raise HTTPException(status_code=422, detail=f"Mission not available: {body.mission}")
    if body.cheap:
        seats = [s.model_copy(update={"model_id": runs.cheap_model()}) for s in seats]
    run_id = await runs.start_run(
        body.goal, seats, budget_usd=body.budget_usd, max_rounds=body.max_rounds,
        mission=body.mission, owner_id=user.id,
    )
    return {"run_id": run_id}


def _run_dict(run: Run, user: User | None = None) -> dict:
    return {
        "id": run.id, "goal": run.goal, "status": run.status, "phase": run.phase,
        "budget_usd": run.budget_usd, "spent_usd": run.spent_usd,
        "created_at": run.created_at.isoformat(), "public": run.public, "site_key": run.site_key,
        "can_change": auth.can_change(user, run), "live": runs.get_active(run.id) is not None,
    }


def readable_run(run_id: str, user: User | None = Depends(optional_user),
                 session: Session = Depends(get_session)) -> Run:
    run = session.get(Run, run_id)
    if not run or not auth.can_read(user, run):
        # Not found and not yours look the same, so run ids can't be probed.
        raise HTTPException(status_code=404 if run is None or user is not None else 401,
                            detail="Run not found" if user is not None or run is None else "Log in first.")
    return run


def changeable_run(run_id: str, user: User | None = Depends(optional_user),
                   session: Session = Depends(get_session)) -> Run:
    run = readable_run(run_id, user, session)
    if not auth.can_change(user, run):
        raise HTTPException(status_code=403, detail="You can watch this run but not change it.")
    return run


@app.get("/api/runs")
def list_runs(user: User = Depends(current_user), session: Session = Depends(get_session)) -> list[dict]:
    mine = Run.owner_id == user.id
    if user.is_owner:
        mine = mine | Run.owner_id.is_(None)
    rows = session.exec(
        select(Run).where(Run.phase != "test", Run.public == False, mine)  # noqa: E712
        .order_by(Run.created_at.desc()).limit(30)
    ).all()
    return [_run_dict(r, user) for r in rows]


@app.get("/api/demos")
def list_demos(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.exec(select(Run).where(Run.public == True).order_by(Run.created_at)).all()  # noqa: E712
    return [_run_dict(r) for r in rows]


@app.get("/api/runs/{run_id}")
def get_run(run: Run = Depends(readable_run), user: User | None = Depends(optional_user)) -> dict:
    return _run_dict(run, user)


@app.get("/api/runs/{run_id}/events")
def run_event_log(run: Run = Depends(readable_run), session: Session = Depends(get_session)) -> list[dict]:
    """The whole event log with timestamps, for Replay."""
    rows = session.exec(select(Event).where(Event.run_id == run.id).order_by(Event.seq)).all()
    return [{"seq": r.seq, "type": r.type, "payload": json.loads(r.payload_json),
             "at": auth._aware(r.at).timestamp()} for r in rows]


class ControlIn(BaseModel):
    action: Literal["pause", "resume", "stop"]


@app.post("/api/runs/{run_id}/control")
def control_run(run_id: str, body: ControlIn, _: Run = Depends(changeable_run)) -> dict:
    active = runs.get_active(run_id)
    if not active:
        raise HTTPException(status_code=409, detail="Run is not in progress")
    if body.action == "stop":
        runs.stop(run_id)
    elif body.action == "pause":
        active.control.pause()
    else:
        active.control.resume()
    return {"ok": True}


class BudgetIn(BaseModel):
    action: Literal["raise", "stop"]
    cap_usd: float | None = Field(default=None, gt=0, le=50)


@app.post("/api/runs/{run_id}/budget")
def answer_budget(run_id: str, body: BudgetIn, _: Run = Depends(changeable_run)) -> dict:
    active = runs.get_active(run_id)
    if not active:
        raise HTTPException(status_code=409, detail="Run is not in progress")
    if body.action == "raise" and not body.cap_usd:
        raise HTTPException(status_code=422, detail="cap_usd is required to raise the cap")
    if not active.answer_budget(body.cap_usd if body.action == "raise" else None):
        raise HTTPException(status_code=409, detail="The run is not waiting at the budget cap")
    return {"ok": True}


class CheckpointIn(BaseModel):
    action: Literal["pick", "another_round", "accept", "changes", "approve"]
    option: str | None = None
    note: str | None = Field(default=None, max_length=2000)
    # plan checkpoint: {task id: {"owner": "B", "reviewer": "C"}}
    assignments: dict[str, dict[str, str]] | None = None


@app.post("/api/runs/{run_id}/checkpoint")
def answer_checkpoint(run_id: str, body: CheckpointIn, _: Run = Depends(changeable_run)) -> dict:
    active = runs.get_active(run_id)
    if not active or not active.checkpoint:
        raise HTTPException(status_code=409, detail="The run is not waiting at a checkpoint")
    kind, payload, _ = active.checkpoint
    if kind == "pick":
        if body.action == "pick":
            if body.option not in {o["id"] for o in payload["options"]}:
                raise HTTPException(status_code=422, detail="Pick one of the options shown")
        elif body.action != "another_round" or not payload.get("can_retry"):
            raise HTTPException(status_code=422, detail="Pick an option")
    elif kind == "plan":
        if body.action != "approve":
            raise HTTPException(status_code=422, detail="Approve the plan (with any swaps)")
        tasks = {task["id"]: task for task in payload["tasks"]}
        seats = set(payload["seats"])
        for tid, change in (body.assignments or {}).items():
            if tid not in tasks:
                raise HTTPException(status_code=422, detail=f"Unknown task {tid}")
            owner = (change.get("owner") or tasks[tid]["owner"] or "").upper()
            reviewer = (change.get("reviewer") or tasks[tid]["reviewer"] or "").upper()
            if owner not in seats or reviewer not in seats:
                raise HTTPException(status_code=422, detail=f"{tid}: pick seats that are at the table")
            if owner == reviewer:
                raise HTTPException(status_code=422, detail=f"{tid}: the reviewer must be a different seat")
    elif kind == "review":
        if body.action not in ("accept", "changes"):
            raise HTTPException(status_code=422, detail="Accept or request changes")
        if body.action == "changes" and not (body.note or "").strip():
            raise HTTPException(status_code=422, detail="Say what should change")
    answer = {"action": body.action}
    if body.option:
        answer["option"] = body.option
    if body.note:
        answer["note"] = body.note.strip()
    if body.assignments:
        answer["assignments"] = body.assignments
    active.answer_checkpoint(answer)
    return {"ok": True}


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@app.post("/api/runs/{run_id}/message")
def send_message(run_id: str, body: MessageIn, _: Run = Depends(changeable_run)) -> dict:
    """The user addresses the council. Seats see it as a direct instruction from the client."""
    active = runs.get_active(run_id)
    if not active:
        raise HTTPException(status_code=409, detail="Run is not in progress")
    entry = active.debate.add_client_message(body.text.strip())
    return {"id": entry.id}


def _run_path(run_id: str, path: str):
    try:
        target = sandbox.safe_path(run_id, path)
    except sandbox.SandboxError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return target


@app.get("/api/runs/{run_id}/files/{path:path}", response_class=PlainTextResponse)
def run_file(path: str, inline: bool = False, run: Run = Depends(readable_run)):
    """Any file in the run folder, as text: inline for the Vault's code view, else a download."""
    target = _run_path(run.id, path)
    headers = {"X-Content-Type-Options": "nosniff"}
    if not inline:
        headers["Content-Disposition"] = f'attachment; filename="{target.name}"'
    media = "text/markdown; charset=utf-8" if target.suffix == ".md" else "text/plain; charset=utf-8"
    return PlainTextResponse(target.read_text(encoding="utf-8", errors="replace"), media_type=media,
                             headers=headers)


@app.get("/api/runs/{run_id}/tree")
def run_tree(run: Run = Depends(readable_run)) -> list[dict]:
    root = sandbox.run_dir(run.id)
    return [
        {"path": p.relative_to(root).as_posix(), "size": p.stat().st_size}
        for p in sorted(root.rglob("*")) if p.is_file()
    ]


SITE_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".json": "application/json",
    ".md": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8",
    ".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg",
}


@app.get("/api/sites/{site_key}/{path:path}")
def run_site(site_key: str, path: str, session: Session = Depends(get_session)):
    """The built site, for the Vault's preview. It is shown in a sandboxed iframe whose opaque
    origin gets no login cookie, so the unguessable site key in the URL is the permission (only
    someone who can read the run can learn it). The CSP stops the site's scripts from making
    network requests or being framed anywhere else."""
    run = session.exec(select(Run).where(Run.site_key == site_key)).first() if len(site_key) >= 16 else None
    if not run:
        raise HTTPException(status_code=404, detail="File not found")
    target = _run_path(run.id, f"site/{path or 'index.html'}")
    site_root = sandbox.run_dir(run.id) / "site"
    if site_root not in target.parents:
        raise HTTPException(status_code=404, detail="File not found")
    csp = (
        "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self' data:; connect-src 'none'; form-action 'none'; "
        f"base-uri 'none'; frame-ancestors 'self' {get_settings().frontend_origin}"
    )
    return Response(
        target.read_bytes(), media_type=SITE_TYPES.get(target.suffix.lower(), "text/plain; charset=utf-8"),
        headers={"Content-Security-Policy": csp, "X-Content-Type-Options": "nosniff",
                 "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@app.websocket("/api/runs/{run_id}/ws")
async def run_events(websocket: WebSocket, run_id: str):
    """Sends every stored event, then a `caught_up` marker, then live events as they happen."""
    origin = websocket.headers.get("origin")
    if origin and origin != get_settings().frontend_origin:
        await websocket.close(code=1008)
        return
    with Session(get_engine()) as session:
        user = auth.user_from_token(session, websocket.cookies.get(auth.COOKIE))
        run = session.get(Run, run_id)
        allowed = run is not None and auth.can_read(user, run)
    await websocket.accept()
    if not allowed:
        await websocket.close(code=4401 if user is None else 4404)
        return
    queue = bus.subscribe(run_id)  # subscribe first so nothing falls between history and live
    try:
        with Session(get_engine()) as session:
            rows = session.exec(
                select(Event).where(Event.run_id == run_id).order_by(Event.seq)
            ).all()
        last = 0
        for row in rows:
            await websocket.send_json(
                {"seq": row.seq, "type": row.type, "payload": json.loads(row.payload_json)}
            )
            last = row.seq
        await websocket.send_json({"seq": last, "type": "caught_up", "payload": {}})

        disconnected = asyncio.create_task(_wait_disconnect(websocket))
        while True:
            getter = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({getter, disconnected}, return_when=asyncio.FIRST_COMPLETED)
            if disconnected in done:
                getter.cancel()
                break
            event = getter.result()
            if event["seq"] <= last:
                continue
            await websocket.send_json(
                {"seq": event["seq"], "type": event["type"], "payload": event["payload"]}
            )
            last = event["seq"]
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(run_id, queue)


async def _wait_disconnect(websocket: WebSocket) -> None:
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        return
