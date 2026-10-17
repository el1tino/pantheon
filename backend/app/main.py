from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.config import APP_NAME, get_settings
from app.db import Message, Run, get_session, init_db
from app.gateway import openrouter


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
