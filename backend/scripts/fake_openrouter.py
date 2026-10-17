"""A stand-in for OpenRouter that streams scripted debate replies. No keys, no cost.

Use it to work on the Chamber or film it without spending anything:

    uv run python scripts/fake_openrouter.py            # listens on http://127.0.0.1:9100
    OPENROUTER_BASE_URL=http://127.0.0.1:9100/v1 OPENROUTER_API_KEY=fake \
        uv run uvicorn app.main:app --port 8000

Replies come from app/devtools/council_script.py and cover every mission step: detecting
the mission, options and scoring, nominations and role votes, writing, critique, revision,
debate rounds and the moderator's verdict.
Options: --port, --cps (characters streamed per second), --fail <model id> (repeatable).
"""

import argparse
import json
import random
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `app` imports from scripts/
from app.devtools.council_script import reply

PRICE_IN, PRICE_OUT = 3e-7, 1.2e-6


class Handler(BaseHTTPRequestHandler):
    cps = 140.0
    fail: set[str] = set()

    def log_message(self, *args):
        pass

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            with open(_seats_file()) as f:
                from_yaml = re.findall(r"model_id: (\S+?),", f.read())
            ids = set(from_yaml) | {"openai/gpt-4o-mini"}
            self._json(200, {"data": [{"id": i, "pricing": {"prompt": str(PRICE_IN), "completion": str(PRICE_OUT)}}
                                      for i in sorted(ids)]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        model = req["model"]
        if model in self.fail:
            time.sleep(0.8)
            self._json(503, {"error": {"message": f"{model} is unavailable (simulated)", "code": 503}})
            return
        msgs = req["messages"]
        system = msgs[0]["content"]
        # On a retry the last user message is the error; the original prompt is the first one.
        user = next(m["content"] for m in msgs if m["role"] == "user")
        text = reply(system, user)
        prompt_tokens = sum(len(m["content"]) for m in msgs) // 4
        completion_tokens = len(text) // 4
        usage = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                 "total_tokens": prompt_tokens + completion_tokens,
                 "cost": round(prompt_tokens * PRICE_IN + completion_tokens * PRICE_OUT, 8)}
        time.sleep(random.uniform(0.5, 1.4))  # "thinking"
        if not req.get("stream"):
            self._json(200, {"id": "fake", "object": "chat.completion", "created": int(time.time()), "model": model,
                             "choices": [{"index": 0, "finish_reason": "stop",
                                          "message": {"role": "assistant", "content": text}}],
                             "usage": usage})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def send(obj) -> None:
            self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode())
            self.wfile.flush()

        base = {"id": "fake", "object": "chat.completion.chunk", "created": int(time.time()), "model": model}
        step = 6
        for i in range(0, len(text), step):
            send({**base, "choices": [{"index": 0, "delta": {"content": text[i:i + step]}, "finish_reason": None}]})
            time.sleep(step / self.cps)
        send({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        send({**base, "choices": [], "usage": usage})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def _seats_file() -> str:
    from pathlib import Path

    return str(Path(__file__).resolve().parents[2] / "config" / "seats.yaml")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--cps", type=float, default=140.0, help="characters streamed per second")
    parser.add_argument("--fail", action="append", default=[], help="model id that always errors")
    args = parser.parse_args()
    Handler.cps = args.cps
    Handler.fail = set(args.fail)
    print(f"Fake OpenRouter on http://127.0.0.1:{args.port}/v1 (cps={args.cps}, failing={sorted(Handler.fail) or 'none'})")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
