# CLAUDE.md

Pantheon is a web app where chat models from many providers sit as a council, debate a user's goal, split the work by strength and build the result while the user watches the live "Chamber" UI. A run can be any everyday AI job, not just a business launch: each run has a **mission** (Ask, Write, Plan, Decide, Learn, Build, Create, Launch) that sets its phases, checkpoints and deliverable. **The full spec is `PANTHEON_SPEC.md`. Read it before you start any milestone.**

## Working rules

- **One milestone at a time.** Build milestones in order (see below). Plan each one and get the user's approval before writing code. When it runs, give the exact commands to run it, commit, and stop. Don't start the next milestone until the user says so.
- **The app name lives in one config constant.** "Pantheon" is a placeholder. Backend: `backend/app/config.py` (`APP_NAME`). Frontend: one shared constant that reads it or mirrors it. Never hard-code the name anywhere else.
- **Never put API keys in frontend code.** Keys live only in the backend `.env`. The browser never calls a model directly.
- Use cheap models and a low budget cap for development runs.

## Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js, React, TypeScript, Tailwind CSS, Framer Motion, PixiJS (effects canvas) |
| Backend | Python 3.12, FastAPI, asyncio, Pydantic |
| Models | OpenRouter through the OpenAI Python SDK. Image provider APIs are called directly |
| Storage | SQLite first (Postgres later). Run files go in `projects/<run_id>/` |
| Code execution | One Docker container per run |
| Hosting | Local first, then Railway, Render, Fly.io or a VPS |

The frontend only displays. The backend orchestrator makes every decision. The UI animates purely from WebSocket events, and Replay and Demo mode re-send stored events.

## Folder layout

```
pantheon/
  backend/
    app/
      orchestrator/   # phases, rounds, voting, budget
      gateway/        # OpenRouter + image API clients
      events/         # event log + WebSocket
      db/             # models and migrations
  frontend/           # Next.js app: Chamber, Board, Vault, Replay
  projects/           # one folder per run (git-ignored)
  config/seats.yaml   # 13 seats: letter, name, provider, model ID, colour, voice ID, sensitive_ok (no fixed roles)
  PANTHEON_SPEC.md
  CLAUDE.md
  .env.example
```

## Core contracts (details in the spec)

- **Agent reply format:** JSON with `stance` (propose | challenge | agree | vote | report | question), `reply_to`, `content`, an optional `proposal` and optional `votes`. It is validated with Pydantic. An invalid reply is retried once with the error shown, then dropped.
- **DB tables:** runs, seats, messages, votes, tasks, artifacts, events.
- **Event types:** phase_changed, seat_thinking, token, message_done, vote_cast, task_updated, artifact_created, cost_updated, checkpoint_opened, checkpoint_resolved, message_routed, diff_applied.

## Guardrails (never break these)

- **Hard budget cap:** estimate each call's cost before sending it and record the cost after. At 80% of the cap the cost meter turns amber. At 100% the run pauses and asks the user.
- **Round limits:** each discussion phase gets at most 3 rounds by default. If there's no agreement by then, the moderator decides by majority vote.
- **Sandboxed files:** agents write only inside `projects/<run_id>/`. Reject any path that resolves outside it.
- **Sandboxed code:** generated code runs only in Docker, with no host files or secrets and with a timeout.
- **Secrets stay on the server:** they are never sent to the browser or to any model.
- **Sensitive files:** a seat with `sensitive_ok: false` never receives files marked private.
- **Fact-checking:** a claim with no proof (an artifact or log) is marked unverified in the UI.
- **Model failure:** a seat whose provider fails shows as absent, its tasks are reassigned, and the run continues.

## Milestones

1. **Skeleton:** FastAPI, Next.js, SQLite, `.env`, one OpenRouter call end to end. Done when a test page shows a reply from one model.
2. **Debate engine:** seats, the reply format, rounds with limits, moderator summary, cost tracking. Done when 4 models debate in the terminal and the transcript is saved.
3. **The Chamber, live:** WebSocket, letter arc, project core with +/− counters, lines, arrows, seat states, transcript, phase rail, cost meter. Use the frontend design skill and treat the spec's Chamber section as the design brief.
4. **Missions, ideas, voting and checkpoints:** mission picker and Auto detection, anonymous scoring, checkpoint cards, user messages, and the text missions (Ask, Write, Plan, Decide, Learn) end to end.
5. **Roles and building:** models nominate themselves for workstreams and vote on who does what (no fixed roles, no self-votes), the Board and the Vault.
6. **Images and integration:** Docker execution and the consistency pass.
7. **Replay, Demo mode and deployment.**

Commit after each milestone works.
