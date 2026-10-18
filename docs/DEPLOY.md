# Deploying Pantheon

The app runs on one small Linux server (a VPS) with Docker Compose. Caddy sits in front and gets an HTTPS certificate by itself, so the app is reachable from any phone or laptop at `https://your-domain`.

```
browser ──HTTPS──▶ Caddy ──/api/* and the WebSocket──▶ backend (FastAPI, :8000)
                         └─everything else──────────▶ frontend (Next.js, :3000)
backend ──host Docker socket──▶ one locked-down runner container per site check
```

## What you need

- A VPS with 2 GB of RAM or more and Docker Engine with the Compose plugin. Hetzner, DigitalOcean, Linode and Vultr all work. A $5–10 a month server is enough.
- A domain or subdomain with an `A` record pointing at the server's IP, for example `assembly.example.com`.
- Ports 80 and 443 open. Caddy needs both to get the certificate.
- An OpenRouter key with a spending limit set on openrouter.ai.

## 1. Get the code and the folders ready

```bash
git clone <your repo url> pantheon && cd pantheon
sudo mkdir -p /srv/pantheon/data /srv/pantheon/projects
sudo chown -R 1000:1000 /srv/pantheon   # the backend runs as uid 1000
getent group docker | cut -d: -f3        # note this number: DOCKER_GID below
```

## 2. Fill in `.env`

```bash
cp .env.example .env
nano .env
```

Set at least:

| Setting | Value |
|---|---|
| `DOMAIN` | your domain, e.g. `assembly.example.com` (no `https://`) |
| `DOCKER_GID` | the number from `getent group docker` |
| `OPENROUTER_API_KEY` | your key |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | the owner account, created on first start. The password needs 10+ characters. |

The compose file sets `FRONTEND_ORIGIN=https://$DOMAIN`, `COOKIE_SECURE=true`, the database path and the projects path for you. Don't set them in `.env` for this setup.

After the first start you can remove `ADMIN_PASSWORD` from `.env`. The account stays, and the password is stored only as an Argon2 hash.

## 3. Start it

```bash
docker compose up -d --build
docker compose logs -f backend      # Ctrl+C to stop following
```

The first build takes a few minutes. The `runner` service builds the sandbox image (`pantheon-runner:1`) and exits. That is expected.

Open `https://your-domain`, log in with the owner account and press **Invite someone** to get a one-use invite link. It expires in a week. Nobody can sign up without one.

## Updating

```bash
git pull
docker compose up -d --build
```

The database, run folders and Caddy's certificates live outside the containers (`/srv/pantheon` and the `caddy_data` volume), so they survive rebuilds. New database columns are added on start.

## Backups

Everything worth keeping is in `/srv/pantheon`:

```bash
sudo tar czf pantheon-backup-$(date +%F).tgz -C /srv pantheon
```

## A public demo link

To show the app without anyone spending money, run a second copy with `DEMO_MODE=true`. New runs are switched off. Visitors see the recorded demo in `demo/` and can replay it without logging in. Nothing is sent to any model, so it doesn't need an OpenRouter key.

To record your own demo, finish a run, then:

```bash
docker compose exec backend .venv/bin/python -m app.cli export-demo RUN_ID launch
```

This writes `demo/launch/` inside the container. Copy it out with `docker compose cp backend:/app/demo/launch ./demo/` and commit it. Each folder in `demo/` is imported as a public, read-only run on start.

## Security notes

- **The Docker socket.** The backend starts runner containers through the host's Docker daemon, so it gets the socket. Anything with the socket can control the host's Docker, which is root-level access. The backend is the only service that has it, and it is never exposed directly: only Caddy is published, and only `/api/*` reaches the backend. The runner containers themselves have no network, a read-only filesystem, no capabilities, no secrets, a memory, CPU and process limit and a timeout. If you don't want the backend to hold the socket, remove that volume line. Runs still finish, but sites are marked as not run.
- **Same path inside and out.** The host's Docker daemon mounts a run's `site/` folder into the runner by its path. That's why `/srv/pantheon/projects` is mounted at the same path inside the backend container. Change both sides together if you move it.
- **Keys** live only in `.env` on the server. They are never sent to the browser or to any model.
- **Login.** Passwords are Argon2-hashed. Sessions are random tokens stored only as SHA-256 hashes, in an HttpOnly, Secure, SameSite=Lax cookie. Failed logins are rate-limited per email and per address. Writes from any other origin are refused.
- **Site previews** are served from a hard-to-guess per-run URL under `/api/sites/`, with a strict Content Security Policy. They load in a sandboxed iframe that can't read the app's cookies or make network requests.

## Running without Compose

You can also run it by hand on any host. Run the backend with `uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers` and the frontend with `npm run build && npm start`. Then put any reverse proxy in front that sends `/api/*` (including WebSocket upgrades) to :8000 and everything else to :3000. Set `FRONTEND_ORIGIN=https://your-domain` and `COOKIE_SECURE=true`.

Railway, Render and Fly.io can host the frontend and backend too. Those platforms don't give the backend a Docker daemon, though, so the Integrate phase there reports sites as not run.
