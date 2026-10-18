import asyncio
import json
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app import runs
from app.config import APP_NAME, get_settings
from app.db import Event, Message, Run, get_session, init_db
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
    yield


app = FastAPI(title=APP_NAME, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {
        "app": APP_NAME,
        "status": "ok",
        "openrouter_key_set": bool(get_settings().openrouter_api_key),
    }


@app.get("/api/config/public")
def public_config() -> dict:
    # Only non-secret values belong here; this is sent to the browser.
    return {"app_name": APP_NAME}


class TestCallIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


class TestCallOut(BaseModel):
    run_id: str
    model: str
    reply: str
    tokens: int
    cost_usd: float | None


@app.post("/api/test-call", response_model=TestCallOut)
async def test_call(body: TestCallIn, session: Session = Depends(get_session)):
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
    run = Run(goal=body.prompt, status="done", phase="test", spent_usd=cost)
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
async def create_run(body: RunIn) -> dict:
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
        mission=body.mission,
    )
    return {"run_id": run_id}


def _run_dict(run: Run) -> dict:
    return {
        "id": run.id, "goal": run.goal, "status": run.status, "phase": run.phase,
        "budget_usd": run.budget_usd, "spent_usd": run.spent_usd,
        "created_at": run.created_at.isoformat(),
    }


@app.get("/api/runs")
def list_runs(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.exec(
        select(Run).where(Run.phase != "test").order_by(Run.created_at.desc()).limit(20)
    ).all()
    return [_run_dict(r) for r in rows]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session)) -> dict:
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_dict(run)


class ControlIn(BaseModel):
    action: Literal["pause", "resume", "stop"]


@app.post("/api/runs/{run_id}/control")
def control_run(run_id: str, body: ControlIn) -> dict:
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
def answer_budget(run_id: str, body: BudgetIn) -> dict:
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
def answer_checkpoint(run_id: str, body: CheckpointIn) -> dict:
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
def send_message(run_id: str, body: MessageIn) -> dict:
    """The user addresses the council. Seats see it as a direct instruction from the client."""
    active = runs.get_active(run_id)
    if not active:
        raise HTTPException(status_code=409, detail="Run is not in progress")
    entry = active.debate.add_client_message(body.text.strip())
    return {"id": entry.id}


def _run_path(run_id: str, path: str, session: Session):
    if not session.get(Run, run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        target = sandbox.safe_path(run_id, path)
    except sandbox.SandboxError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return target


@app.get("/api/runs/{run_id}/files/{path:path}", response_class=PlainTextResponse)
def run_file(run_id: str, path: str, inline: bool = False, session: Session = Depends(get_session)):
    """Any file in the run folder, as text: inline for the Vault's code view, else a download."""
    target = _run_path(run_id, path, session)
    headers = {"X-Content-Type-Options": "nosniff"}
    if not inline:
        headers["Content-Disposition"] = f'attachment; filename="{target.name}"'
    media = "text/markdown; charset=utf-8" if target.suffix == ".md" else "text/plain; charset=utf-8"
    return PlainTextResponse(target.read_text(encoding="utf-8", errors="replace"), media_type=media,
                             headers=headers)


@app.get("/api/runs/{run_id}/tree")
def run_tree(run_id: str, session: Session = Depends(get_session)) -> list[dict]:
    if not session.get(Run, run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    root = sandbox.run_dir(run_id)
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


@app.get("/api/runs/{run_id}/site/{path:path}")
def run_site(run_id: str, path: str, session: Session = Depends(get_session)):
    """The built site, for the Vault's preview. It is shown in a sandboxed iframe, and this
    policy stops its scripts from making network requests or being framed anywhere else."""
    target = _run_path(run_id, f"site/{path or 'index.html'}", session)
    site_root = sandbox.run_dir(run_id) / "site"
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
    await websocket.accept()
    queue = bus.subscribe(run_id)  # subscribe first so nothing falls between history and live
    try:
        with Session(get_engine()) as session:
            if not session.get(Run, run_id):
                await websocket.close(code=4404)
                return
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
