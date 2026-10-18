# The API and orchestrator. Built from the repo root: docker build -f backend/Dockerfile .
FROM python:3.12-slim

# The Docker CLI only: the backend starts one locked-down runner container per site check
# through the host's Docker daemon (see docs/DEPLOY.md for what that means).
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
RUN pip install --no-cache-dir "uv>=0.8,<1"

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/app ./app
COPY config /app/config
COPY --chown=1000:1000 demo /app/demo

RUN useradd --create-home --uid 1000 app
USER app
EXPOSE 8000
# Caddy is the only client, so its X-Forwarded-For is trusted for the login rate limit.
CMD ["/app/backend/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
