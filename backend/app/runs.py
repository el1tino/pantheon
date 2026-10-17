"""Starts debates in the background and holds the controls for runs in progress."""

import asyncio
import logging
import time
from dataclasses import dataclass, field

from sqlmodel import Session

from app.config import get_settings
from app.db.session import get_engine
from app.events import bus
from app.gateway import openrouter
from app.orchestrator.budget import Budget, BudgetExceeded
from app.orchestrator.debate import ChatFn, Debate, RunControl
from app.orchestrator.seats import SeatConfig

log = logging.getLogger(__name__)

PRICE_CACHE_S = 3600
_prices: dict[str, tuple[float, float]] = {}
_prices_at = 0.0


async def get_prices() -> dict[str, tuple[float, float]]:
    global _prices, _prices_at
    if not _prices or time.monotonic() - _prices_at > PRICE_CACHE_S:
        try:
            _prices = await openrouter.fetch_prices()
            _prices_at = time.monotonic()
        except openrouter.GatewayError as exc:
            log.warning("%s; using fallback prices for estimates", exc)
    return _prices


@dataclass
class ActiveRun:
    debate: Debate
    control: RunControl
    task: asyncio.Task | None = None
    budget_answer: asyncio.Future | None = field(default=None)

    def answer_budget(self, new_cap: float | None) -> bool:
        if self.budget_answer is None or self.budget_answer.done():
            return False
        self.budget_answer.set_result(new_cap)
        return True


_active: dict[str, ActiveRun] = {}


def get_active(run_id: str) -> ActiveRun | None:
    return _active.get(run_id)


async def start_run(
    goal: str,
    seats: list[SeatConfig],
    *,
    budget_usd: float,
    max_rounds: int,
    chat: ChatFn | None = None,
) -> str:
    prices = await get_prices()
    session = Session(get_engine())
    control = RunControl()
    active: ActiveRun | None = None

    async def ask_budget(budget: Budget, exc: BudgetExceeded) -> float | None:
        assert active is not None
        active.budget_answer = asyncio.get_running_loop().create_future()
        return await active.budget_answer

    debate = Debate(
        session, goal, seats, budget_usd=budget_usd, max_rounds=max_rounds, phase="ideas",
        chat=chat, prices=prices, on_budget_pause=ask_budget, control=control,
    )
    debate.log.subscribe(bus.publish)
    active = ActiveRun(debate=debate, control=control)
    run_id = debate.run_id
    _active[run_id] = active

    async def runner() -> None:
        try:
            await debate.run_debate()
        except Exception as exc:  # keep the server alive and tell the UI
            log.exception("Run %s failed", run_id)
            debate.run.status = "failed"
            session.add(debate.run)
            session.commit()
            debate.log.emit("phase_changed", phase=debate.phase, status="failed", error=str(exc))
        finally:
            session.close()
            _active.pop(run_id, None)

    active.task = asyncio.create_task(runner())
    return run_id


def stop(run_id: str) -> bool:
    active = _active.get(run_id)
    if not active:
        return False
    active.control.stop()
    active.answer_budget(None)  # a run waiting at the budget card stops too
    return True


def cheap_model() -> str:
    return get_settings().default_model
