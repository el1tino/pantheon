"""A stand-in for OpenRouter that streams scripted debate replies. No keys, no cost.

Use it to work on the Chamber or film it without spending anything:

    uv run python scripts/fake_openrouter.py            # listens on http://127.0.0.1:9100
    OPENROUTER_BASE_URL=http://127.0.0.1:9100/v1 OPENROUTER_API_KEY=fake \
        uv run uvicorn app.main:app --port 8000

Replies follow the debate protocol: everyone proposes, then seats challenge, question,
revise and agree, converging on one idea (or splitting into a vote, depending on the goal).
Options: --port, --cps (characters streamed per second), --fail <model id> (repeatable).
"""

import argparse
import hashlib
import json
import random
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PRICE_IN, PRICE_OUT = 3e-7, 1.2e-6

ANGLES = [
    ("Studio", "a premium, design-led take aimed at professionals who pay for quality"),
    ("Collective", "a community-first model where members fund and shape the roadmap"),
    ("Express", "the fastest, cheapest version that ships in a week and learns from usage"),
    ("Atlas", "a data-rich guide that turns expertise into a subscription product"),
    ("Forge", "a B2B tool that teams adopt bottom-up, priced per seat"),
    ("Kit", "a done-for-you starter bundle with templates and onboarding"),
    ("Pulse", "a mobile-first habit product with daily touchpoints and streaks"),
    ("Exchange", "a two-sided marketplace that takes a small cut of each match"),
]
CHALLENGES = [
    "The unit economics don't work below a few thousand paying users. Where does acquisition come from?",
    "This is crowded. Three incumbents already do it, and none of them charge enough to copy.",
    "Too broad for a first launch. Pick one customer and one painful job, or we build mush.",
    "The pricing assumes people pay monthly for something they use twice a year.",
    "It depends on partnerships we can't sign from a laptop. That's a risk, not a plan.",
]
AGREES = [
    "This is the one. Narrow enough to ship, with a clear path to revenue.",
    "Agreed. It plays to what this council can actually build end to end.",
    "I'm convinced. The positioning is sharp and the first version is small.",
    "Backing this. The challenge was fair, and the answer holds up.",
]
QUESTIONS = [
    "Who exactly is the first customer, and where do they hang out online?",
    "What's the one metric that tells us in week two whether this works?",
    "How does this make money before it has scale?",
]
REVISIONS = [
    "Taking the challenge on board: same core, but launch to one niche first and charge from day one.",
    "Revised: cut the scope to a single flagship feature and a waitlist page.",
]


def _keyword(goal: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z]{4,}", goal)
             if w.lower() not in {"come", "with", "idea", "create", "everything", "business",
                                  "that", "this", "build", "make", "name", "startup", "about"}]
    return words[-1].capitalize() if words else "Venture"


class Script:
    """Decides what each seat says, from the prompt alone, so replies stay consistent."""

    def __init__(self, system: str, user: str):
        self.system, self.user = system, user
        self.goal = re.search(r"GOAL: (.*)", user).group(1) if "GOAL:" in user else ""
        m = re.search(r"seat ([A-M]) on the", system)
        self.letter = m.group(1) if m else "?"
        seed = int(hashlib.sha256(f"{self.goal}|{self.letter}".encode()).hexdigest(), 16)
        self.rng = random.Random(seed)
        self.goal_rng = random.Random(int(hashlib.sha256(self.goal.encode()).hexdigest(), 16))
        self.entries = re.findall(r"^\[(m\d+)\] ([A-M]) \S+ \((\w+)(?: -> (m\d+))?\)", user, re.M)

    def proposals(self) -> list[tuple[str, str]]:
        return [(mid, seat) for mid, seat, stance, _ in self.entries if stance == "propose"]

    def favourite(self) -> str | None:
        """The proposal the council is leaning towards: most agreements, earliest on ties."""
        props = self.proposals()
        if not props:
            return None
        backing = {mid: 0 for mid, _ in props}
        for _, _, stance, to in self.entries:
            if stance == "agree" and to in backing:
                backing[to] += 1
        # Seed the lean from the goal so different goals pick different winners.
        bias = self.goal_rng.randrange(len(props))
        return max(props, key=lambda p: (backing[p[0]], -((props.index(p) - bias) % len(props))))[0]

    def reply(self) -> str:
        if "neutral moderator" in self.system:
            return self.moderator()
        if "VOTE ROUND" in self.user:
            options = re.findall(r"- (m\d+) by ([A-M])", self.user.split("VOTE ROUND")[1])
            fav = self.favourite()
            pick = next((m for m, s in options if m == fav), options[0][0])
            return self._json("vote", None, f"My vote goes to {pick}: it is the most buildable option on the table.",
                              votes=[{"target": pick, "score": 1}])
        rnd = int(re.search(r"ROUND (\d+) of (\d+)", self.user).group(1))
        self.rng = random.Random(f"{self.goal}|{self.letter}|{rnd}")
        if rnd == 1:
            word, angle = ANGLES[self.rng.randrange(len(ANGLES))]
            title = f"{_keyword(self.goal)} {word}"
            return self._json("propose", None, f"I propose {title}: {angle}.",
                              proposal={"title": title, "summary": angle[0].upper() + angle[1:] + "."})
        others = [(m, s) for m, s in self.proposals() if s != self.letter]
        fav = self.favourite()
        roll = self.rng.random() + rnd * 0.18 + (0.25 if self.goal_rng.random() < 0.5 else -0.15)
        if roll < 0.55 and others:
            target = others[self.rng.randrange(len(others))][0]
            return self._json("challenge", target, CHALLENGES[self.rng.randrange(len(CHALLENGES))])
        if roll < 0.7 and others:
            target = others[self.rng.randrange(len(others))][0]
            return self._json("question", target, QUESTIONS[self.rng.randrange(len(QUESTIONS))])
        if roll < 0.8 and rnd == 2:
            word, angle = ANGLES[self.rng.randrange(len(ANGLES))]
            title = f"{_keyword(self.goal)} {word}"
            return self._json("propose", None, REVISIONS[self.rng.randrange(len(REVISIONS))],
                              proposal={"title": title, "summary": angle[0].upper() + angle[1:] + "."})
        return self._json("agree", fav, AGREES[self.rng.randrange(len(AGREES))])

    def moderator(self) -> str:
        if "vote is tied" in self.user:
            first = re.findall(r"- (m\d+) by", self.user)[0]
            return json.dumps({"winner": first, "reason": "It drew the fewest unanswered objections."})
        m = re.search(r"Decision: \[(m\d+)\] by ([A-M]): ([^\n]*?) \(reached by (\w+)\)", self.user)
        title, how = (m.group(3), m.group(4)) if m else ("no proposal", "none")
        return (
            f"**Decision**\n\n{title}, reached by {how}.\n\n"
            "**Why**\n\nIt is the narrowest idea with a believable path to paying customers, "
            "and the council can build a first version itself.\n\n"
            "**Open objections**\n\n- Customer acquisition cost is still a guess.\n"
            "- Pricing needs testing with real users.\n\n"
            "**Next steps**\n\n- Research competitors and pricing.\n- Draft the brand and a landing page."
        )

    @staticmethod
    def _json(stance, reply_to, content, proposal=None, votes=None) -> str:
        return json.dumps({"stance": stance, "reply_to": reply_to, "content": content,
                           "proposal": proposal, "votes": votes}, indent=1)


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
        text = Script(system, user).reply()
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
