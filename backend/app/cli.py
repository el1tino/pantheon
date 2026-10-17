"""Terminal entry point.

    uv run python -m app.cli debate "Your goal" --seats A,B,C,D --rounds 3 --budget 0.25

The terminal view is drawn purely from the run's events, the same stream the Chamber will use.
"""

import argparse
import asyncio
import sys
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text
from sqlmodel import Session

from app.config import APP_NAME, get_settings
from app.db.session import get_engine, init_db
from app.gateway import openrouter
from app.orchestrator.budget import Budget, BudgetExceeded, usd
from app.orchestrator.debate import MODERATOR, Debate
from app.orchestrator.seats import SeatConfig, pick_seats

STANCE_LABEL = {
    "propose": "Proposes", "challenge": "Challenges", "agree": "Agrees", "vote": "Votes",
    "report": "Reports", "question": "Asks",
}
AMBER = "#F5A524"


class TerminalView:
    def __init__(self, console: Console, seats: list[SeatConfig]):
        self.console = console
        self.seats = {s.letter: s for s in seats}
        self.warned = False
        self.max_rounds: int | None = None

    def _seat(self, letter: str) -> tuple[str, str]:
        if letter == MODERATOR:
            return "Moderator", "white"
        s = self.seats[letter]
        return f"{s.letter} · {s.name}", s.colour

    def __call__(self, event: dict[str, Any]) -> None:
        t, p = event["type"], event["payload"]
        c = self.console
        if t == "phase_changed":
            self.max_rounds = p.get("max_rounds", self.max_rounds)
            if p.get("round") == "vote":
                c.rule("[bold]Vote round[/]")
            elif p.get("round"):
                c.rule(f"[bold]Round {p['round']}[/] of {self.max_rounds}")
        elif t == "seat_thinking" and p["state"] == "absent":
            name, colour = self._seat(p["seat"])
            c.print(f"[dim]{name} is absent: {p.get('error', '')}[/]", style=colour)
        elif t == "seat_thinking" and p["state"] == "retrying":
            name, _ = self._seat(p["seat"])
            c.print(f"[yellow]  {name}'s reply was invalid, retrying: {p['error']}[/]")
        elif t == "seat_thinking" and p["state"] == "thinking":
            name, colour = self._seat(p["seat"])
            c.print(Text(f"  {name} is thinking…", style=f"dim {colour}"))
        elif t == "message_done" and p.get("dropped"):
            name, _ = self._seat(p["seat"])
            c.print(f"[red]  {name}'s reply was dropped after a retry: {p['reason']}[/]")
        elif t == "message_done":
            self._message(p)
        elif t == "vote_cast":
            c.print(f"  [dim]vote[/] {p['voter']} → {p['target']} ({p['target_seat']})")
        elif t == "cost_updated":
            if p["warning"] and not self.warned:
                self.warned = True
                c.print(
                    f"[bold {AMBER}]Budget warning: {usd(p['spent_usd'])} spent, "
                    f"{p['ratio']:.0%} of the {usd(p['cap_usd'])} cap.[/]"
                )
        elif t == "checkpoint_resolved" and p["kind"] == "budget":
            c.print(f"[dim]Budget checkpoint: {p['action']}[/]")

    def _message(self, p: dict[str, Any]) -> None:
        name, colour = self._seat(p["seat"])
        if p["seat"] == MODERATOR:
            self.console.print(
                Panel(Markdown(p["content"]), title="Moderator summary", border_style="white")
            )
            return
        head = Text()
        head.append("▌ ", style=colour)
        head.append(name, style=f"bold {colour}")
        head.append(f"  {STANCE_LABEL.get(p['stance'], p['stance'])}", style="italic")
        if p.get("reply_to"):
            head.append(f" → {p['reply_to']}", style="dim")
        head.append(f"  [{p['id']}]  ${p['cost_usd']:.5f}", style="dim")
        self.console.print(head)
        self.console.print(Text("  " + p["content"]))
        if p.get("proposal"):
            title = p["proposal"].get("title") or ""
            summary = p["proposal"].get("summary") or ""
            self.console.print(Text(f"  ◆ {title}{': ' if title and summary else ''}{summary}", style=colour))
        self.console.print()


def _ask_budget(console: Console):
    async def ask(budget: Budget, exc: BudgetExceeded) -> float | None:
        console.print(
            f"\n[bold red]Budget cap reached.[/] Spent {usd(exc.spent)} of {usd(exc.cap)}; "
            f"the next call is estimated at {usd(exc.estimate)}."
        )
        if not sys.stdin.isatty():
            console.print("[dim]No terminal to ask on; stopping.[/]")
            return None
        answer = Prompt.ask(
            "New cap in dollars, or press Enter to stop", default="", show_default=False
        )
        try:
            return float(answer) if answer.strip() else None
        except ValueError:
            return None

    return ask


async def _debate(args: argparse.Namespace) -> int:
    console = Console()
    seats = pick_seats([x.strip().upper() for x in args.seats.split(",") if x.strip()])
    if args.model_override:
        seats = [s.model_copy(update={"model_id": args.model_override}) for s in seats]

    try:
        prices = await openrouter.fetch_prices()
    except openrouter.GatewayError as exc:
        console.print(f"[dim]{exc}. Using the fallback prices from config for estimates.[/]")
        prices = {}

    init_db()
    with Session(get_engine()) as session:
        debate = Debate(
            session, args.goal, seats, budget_usd=args.budget, max_rounds=args.rounds,
            prices=prices, on_budget_pause=_ask_budget(console),
            moderator_model=args.moderator_model,
        )
        console.print(Panel(
            Text.assemble(
                (f"{APP_NAME} council", "bold"), f"  run {debate.run_id}\n\n",
                ("Goal: ", "bold"), args.goal, "\n",
                *[t for s in seats for t in ((f"\n{s.letter} {s.name}", f"bold {s.colour}"),
                                             f"  {s.role}  ", (s.model_id, "dim"))],
            ),
            border_style="dim",
        ))
        debate.log.subscribe(TerminalView(console, seats))
        result = await debate.run_debate()

    console.rule("[bold]Result[/]")
    if result.decision:
        console.print(f"Decision: [bold]{result.decision.id}[/] by {result.decision.seat} ({result.decided_by})")
    console.print(
        f"Status: {result.status} · cost {usd(result.spent_usd)} of {usd(debate.budget.cap_usd)}"
        f" · absent: {', '.join(result.absent) or 'none'} · dropped replies: {result.dropped}"
    )
    for path in result.transcript_paths:
        console.print(f"Saved {path}")
    return 0 if result.status == "done" else 1


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="app.cli", description=f"{APP_NAME} command line")
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("debate", help="Run a council debate in the terminal")
    d.add_argument("goal")
    d.add_argument("--seats", default="A,B,C,D", help="Seat letters, comma separated")
    d.add_argument("--rounds", type=int, default=settings.max_rounds)
    d.add_argument("--budget", type=float, default=settings.default_budget_usd, help="Cap in USD")
    d.add_argument("--model-override", help="Use this model for every seat (cheap test runs)")
    d.add_argument("--moderator-model", default=settings.moderator_model)
    args = parser.parse_args(argv)
    if args.command == "debate":
        return asyncio.run(_debate(args))
    return 2


if __name__ == "__main__":
    sys.exit(main())
