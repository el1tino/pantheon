# Pantheon

A council of AI models from different providers debates your goal, splits the work and builds the result while you watch. The full spec is in [`PANTHEON_SPEC.md`](PANTHEON_SPEC.md). "Pantheon" is a placeholder name; it lives in `backend/app/config.py` (`APP_NAME`) and `frontend/src/lib/app.ts`.

## Status

- Milestone 1 (Skeleton) is done: FastAPI, Next.js and SQLite, with one OpenRouter call going end to end.
- Milestone 2 (Debate engine) is done: seats debate a goal in the terminal with round limits, a majority vote, a moderator summary and a hard budget cap, and the transcript is saved.

![Test page](docs/milestone-1-test-page.png)

## Requirements

Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 20+ and an [OpenRouter](https://openrouter.ai) key. Set a spending limit on the key.

## Run it

```bash
cp .env.example .env          # then put your key in OPENROUTER_API_KEY

# Terminal 1: backend on :8000
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000

# Terminal 2: frontend on :3000
cd frontend
npm install
npm run dev
```

Open http://localhost:3000/test and press **Send**. The reply, the token count and the cost appear under the box. Each call is saved as a run plus a message in `pantheon.db`.

## Run a debate in the terminal

```bash
cd backend
uv run python -m app.cli debate "Come up with a name and positioning for a coffee subscription startup" \
  --seats A,B,C,D --rounds 3 --budget 0.25
```

- Round 1: every seat proposes. Rounds 2 and 3: seats agree, challenge, propose or question. If every present seat agrees with the same proposal, the debate ends early.
- After the round limit, each seat votes for one proposal that isn't its own and the majority wins. The moderator (`MODERATOR_MODEL`) breaks ties and writes the summary.
- Each call's cost is estimated before it's sent, using OpenRouter's price list, and the real cost is recorded after. At 80% of the cap you get an amber warning. If a call would pass the cap, the run pauses and asks for a new cap, or stops if you press Enter.
- A seat whose provider fails shows as absent and the debate continues. An invalid reply is retried once with the error shown, then dropped.
- The transcript is saved to `projects/<run_id>/transcript.md` and `transcript.json`. Every step is also stored in the `events` table for the live Chamber and Replay later.
- For the cheapest test run, add `--model-override openai/gpt-4o-mini` so every seat uses one cheap model.

The model IDs in `config/seats.yaml` change often. Check them at https://openrouter.ai/models before a real run.

## Checks

```bash
cd backend && uv run pytest        # mocked gateway, no API cost
cd frontend && npm run lint && npm run build
```

## Layout

```
backend/app/config.py      APP_NAME + settings from .env
backend/app/gateway/       OpenRouter client (OpenAI SDK)
backend/app/db/            SQLite tables: runs, seats, messages, votes, tasks, artifacts, events
backend/app/orchestrator/  debate rounds, voting, budget, reply format, file sandbox
backend/app/events/        ordered event log (the WebSocket comes in milestone 3)
backend/app/cli.py         terminal entry point
frontend/                  Next.js app; /api/* is proxied to the backend
config/seats.yaml          the 13 seats (check model IDs at openrouter.ai/models)
projects/                  one folder per run (git-ignored)
```
