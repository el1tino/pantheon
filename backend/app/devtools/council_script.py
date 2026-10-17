"""Scripted council replies for the practice server and the tests. No model involved.

Given the exact prompt a seat or the moderator would receive, `reply()` returns a plausible
answer in the right format, so every mission step can run without an API key. Replies are
seeded from the goal, the seat and the step, so a run is repeatable but goals differ.
"""

import hashlib
import json
import random
import re

ANGLES = [
    ("Studio", "a premium, design-led take aimed at people who pay for quality"),
    ("Collective", "a community-first approach where members shape what comes next"),
    ("Express", "the fastest, cheapest version that ships in a week and learns from use"),
    ("Atlas", "a data-rich guide that turns expertise into something people return to"),
    ("Forge", "a practical, tool-first take that teams adopt bottom-up"),
    ("Kit", "a done-for-you bundle with templates and a gentle start"),
    ("Pulse", "a mobile-first habit with daily touchpoints and streaks"),
    ("Exchange", "a two-sided marketplace that takes a small cut of each match"),
]
CHALLENGES = [
    "This costs more than it saves below a few hundred users. Where do they come from?",
    "This is crowded. Three others already do it, and none of them charge enough to copy.",
    "Too broad for a first version. Pick one person and one painful job, or we build mush.",
    "It assumes people will pay monthly for something they use twice a year.",
    "It depends on partnerships we can't sign from a laptop. That's a risk, not a plan.",
]
AGREES = [
    "This is the one. Narrow enough to deliver, with a clear payoff for the client.",
    "Agreed. It plays to what this council can actually do end to end.",
    "I'm convinced. The angle is sharp and the first version is small.",
    "Backing this. The challenge was fair, and the answer holds up.",
]
QUESTIONS = [
    "Who exactly is this for, and what would make them say yes in the first minute?",
    "What's the one thing that tells us early whether this works?",
    "What does this cost the client in time and money, honestly?",
]
REVISIONS = [
    "Taking the challenge on board: same core, but start with one niche and keep it simple.",
    "Revised: cut the scope to one flagship idea and do it properly.",
]
PART_SETS = {
    "write": ["Opening", "The heart of it", "Close and call to action"],
    "plan": ["Day one", "Day two", "Logistics and costs"],
    "learn": ["The big idea", "A worked example", "Common mistakes"],
    "other": ["Overview", "Details", "Next steps"],
}
STOP = {"come", "with", "idea", "create", "everything", "business", "that", "this", "build", "make",
        "name", "startup", "about", "write", "plan", "help", "want", "should", "which", "what",
        "explain", "could", "would", "launch", "month", "into", "from", "your", "they", "there"}


def _keyword(goal: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z]{4,}", goal) if w.lower() not in STOP | {"week", "today", "days"}]
    return words[-1].capitalize() if words else "Venture"


def _rng(*parts: object) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest(), 16))


def detect(goal: str) -> str:
    g = goal.lower()
    rules = [
        ("launch", r"\b(business|startup|launch|company)\b"),
        ("write", r"\b(write|email|essay|letter|post|story|speech|cover letter|poem|toast)\b"),
        ("plan", r"\b(plan|trip|itinerary|schedule|meal|workout|budget|holiday|vacation|party)\b"),
        ("decide", r"\b(choose|decide|compare|vs\.?|versus|which .* (buy|pick|get)|should i (buy|get))\b"),
        ("learn", r"\b(learn|teach|study|understand|exam|test me|how does)\b"),
        ("build", r"\b(app|website|script|code)\b"),
        ("create", r"\b(logo|illustration|image|picture|drawing)\b"),
    ]
    for key, pattern in rules:
        if re.search(pattern, g):
            return key
    return "ask"


class Script:
    def __init__(self, system: str, user: str):
        self.system, self.user = system, user
        m = re.search(r"GOAL: (.*)", user)
        self.goal = m.group(1) if m else ""
        m = re.search(r"seat ([A-M]) on the", system)
        self.letter = m.group(1) if m else "?"
        step = re.search(r"STEP: ([A-Z ]+?)(?: (p\d+))?\.", user)
        self.step = step.group(1).strip() if step else ""
        self.part = step.group(2) if step else None
        self.rng = _rng(self.goal, self.letter, self.step, self.part)
        self.goal_rng = _rng(self.goal)
        self.entries = re.findall(r"^\[(m\d+)\] ([A-M]) \S+ \((\w+)(?: -> (m\d+))?\)", user, re.M)
        # Debate proposals are the ones rendered with a PROPOSAL line (not options or nominations).
        self.debate_props = set(re.findall(r"^\[(m\d+)\] [A-M] \S+ \(propose\)[^\n]*\n\s+PROPOSAL:", user, re.M))
        self.instruction = user.rsplit("ROUND ", 1)[-1] if "ROUND " in user else user

    # ------------------------------------------------------------ dispatch

    def reply(self) -> str:
        if "neutral moderator" in self.system:
            return self.moderator()
        handler = {
            "OPTIONS": self.options, "SCORE": self.score, "NOMINATE": self.nominate,
            "ROLE VOTE": self.role_vote, "WRITE PART": self.write_part, "CRITIQUE": self.critique,
            "REVISE PART": self.revise_part,
        }.get(self.step)
        if handler:
            return handler()
        if "VOTE ROUND" in self.user:
            return self.vote()
        return self.debate()

    @staticmethod
    def _json(stance, reply_to=None, content="", proposal=None, votes=None) -> str:
        return json.dumps({"stance": stance, "reply_to": reply_to, "content": content,
                           "proposal": proposal, "votes": votes}, indent=1)

    def _idea(self, rng: random.Random) -> tuple[str, str]:
        word, angle = ANGLES[rng.randrange(len(ANGLES))]
        return f"{_keyword(self.goal)} {word}", angle[0].upper() + angle[1:] + "."

    # ------------------------------------------------------------ mission steps

    def options(self) -> str:
        n = 2 if "2 to 3" in self.user or self.rng.random() < 0.6 else 1
        seen, opts = set(), []
        while len(opts) < n:
            title, summary = self._idea(self.rng)
            if title not in seen:
                seen.add(title)
                opts.append({"title": title, "summary": summary})
        return self._json("propose", None, f"Here {'are my options' if n > 1 else 'is my option'}: "
                          + "; ".join(o["title"] for o in opts) + ".", proposal={"options": opts})

    def score(self) -> str:
        ids = re.findall(r"^- (o\d+):", self.user, re.M)
        votes = [{"target": i, "score": 2 + _rng(self.goal, i).randrange(3) + (self.rng.random() < 0.3)}
                 for i in ids]
        for v in votes:
            v["score"] = min(5, v["score"])
        best = max(votes, key=lambda v: v["score"])["target"] if votes else ""
        return self._json("vote", None, f"{best} is the strongest: clear, specific and doable.", votes=votes)

    def nominate(self) -> str:
        ids = re.findall(r"^- (p\d+):", self.user, re.M)
        picks = [i for i in ids if self.rng.random() < 0.45][:2]
        pitch = ("I'm strongest at clear structure and concrete detail." if picks
                 else "I'll sit this one out and review instead.")
        return self._json("propose", None, pitch, proposal={"parts": picks, "pitch": pitch})

    def role_vote(self) -> str:
        votes = []
        for pid, cands in re.findall(r"^- (p\d+) \([^)]*\): ([A-M](?:, [A-M])*)", self.user, re.M):
            options = cands.split(", ")
            votes.append({"part": pid, "target": options[_rng(self.goal, pid).randrange(len(options))]})
        return self._json("vote", None, "Voting for whoever pitched the most concrete approach.", votes=votes)

    def write_part(self) -> str:
        m = re.search(r'Write part p\d+ "([^"]+)"', self.user)
        title = m.group(1) if m else "This part"
        subject = _keyword(self.goal).lower()
        body = (
            f"**{title}.** For a goal like \"{self.goal}\", this section keeps things concrete. "
            f"Start with what matters most about {subject}, then give the client something they can "
            "act on today.\n\n"
            f"- One clear point about {subject}, stated plainly.\n"
            "- A specific example with numbers or times where they help.\n"
            "- A short note on what to watch out for.\n"
        )
        return self._json("report", None, body)

    def critique(self) -> str:
        targets = re.findall(r"^- (m\d+): (p\d+) ([^\n]*?) \(by ([A-M])\)", self.user, re.M)
        if not targets:
            return self._json("agree", None, "Nothing to add.")
        mid, pid, title, owner = targets[self.rng.randrange(len(targets))]
        if self.rng.random() < 0.8:
            return self._json("challenge", mid, f'In "{title}", the line "One clear point" is too vague. '
                              "Name the actual point and add a number the client can check.")
        return self._json("agree", mid, f'"{title}" reads well: specific, short and in the right order.')

    def revise_part(self) -> str:
        m = re.search(r'reply_to "(m\d+)"', self.user)
        title = re.search(r'part p\d+ "([^"]+)"', self.user)
        name = title.group(1) if title else "This part"
        subject = _keyword(self.goal).lower()
        body = (
            f"**{name}.** Revised after the council's notes: for \"{self.goal}\", the key point is "
            f"specific. Lead with the single most useful fact about {subject} and back it with a number.\n\n"
            f"- The main point about {subject}, with one checkable figure.\n"
            "- A worked example the client can copy.\n"
            "- The one mistake to avoid, and how.\n"
        )
        return self._json("report", m.group(1) if m else None, body)

    # ------------------------------------------------------------ debate rounds

    def compared(self) -> list[str]:
        m = re.search(r"Comparing: (.+?)(?:\. Criteria:|\.?$)", self.user, re.M)
        return [n.strip() for n in m.group(1).split(",")] if m else []

    def proposals(self) -> list[tuple[str, str]]:
        return [(mid, seat) for mid, seat, stance, _ in self.entries
                if stance == "propose" and mid in self.debate_props]

    def favourite(self) -> str | None:
        props = self.proposals()
        if not props:
            return None
        backing = {mid: 0 for mid, _ in props}
        for _, _, stance, to in self.entries:
            if stance == "agree" and to in backing:
                backing[to] += 1
        bias = self.goal_rng.randrange(len(props))
        return max(props, key=lambda p: (backing[p[0]], -((props.index(p) - bias) % len(props))))[0]

    def vote(self) -> str:
        options = re.findall(r"- (m\d+) by ([A-M])", self.user.split("VOTE ROUND")[1])
        fav = self.favourite()
        pick = next((m for m, _ in options if m == fav), options[0][0])
        return self._json("vote", None, f"My vote goes to {pick}: it is the most workable option.",
                          votes=[{"target": pick, "score": 1}])

    def debate(self) -> str:
        m = re.search(r"ROUND (\d+) of (\d+)", self.user)
        rnd = int(m.group(1)) if m else 1
        self.rng = _rng(self.goal, self.letter, rnd)
        if rnd == 1:
            title, summary = self._idea(self.rng)
            if "Options and criteria" in self.instruction:
                title, summary = "Options and criteria", "Compare the leading options on cost, quality and fit."
            elif "Recommend one option" in self.instruction:
                names = self.compared() or [title]
                pick = names[self.rng.randrange(len(names))] if self.rng.random() < 0.7 else names[0]
                title, summary = pick, f"{pick} fits the client's criteria best on balance."
            return self._json("propose", None, f"{title}: {summary}", proposal={"title": title, "summary": summary})
        others = [(mid, s) for mid, s in self.proposals() if s != self.letter]
        fav = self.favourite()
        roll = self.rng.random() + rnd * 0.18 + (0.25 if self.goal_rng.random() < 0.5 else -0.15)
        if roll < 0.55 and others:
            return self._json("challenge", others[self.rng.randrange(len(others))][0],
                              CHALLENGES[self.rng.randrange(len(CHALLENGES))])
        if roll < 0.7 and others:
            return self._json("question", others[self.rng.randrange(len(others))][0],
                              QUESTIONS[self.rng.randrange(len(QUESTIONS))])
        if roll < 0.8 and rnd == 2:
            title, summary = self._idea(self.rng)
            compared = self.compared()
            if compared:
                title = compared[-1]
                summary = f"On reflection, {title} is the safer choice for this client."
            return self._json("propose", None, REVISIONS[self.rng.randrange(len(REVISIONS))],
                              proposal={"title": title, "summary": summary})
        return self._json("agree", fav, AGREES[self.rng.randrange(len(AGREES))])

    # ------------------------------------------------------------ moderator

    def moderator(self) -> str:
        if self.step == "DETECT":
            key = detect(self.goal)
            return json.dumps({"mission": key, "reason": f"The goal reads as a {key} job."})
        if self.step == "SPLIT":
            text = self.user.split("STEP: SPLIT", 1)[-1].lower()
            kind = ("plan" if "days" in text or "legs" in text else
                    "learn" if "lesson" in text else "write" if "piece" in text else "other")
            return json.dumps({"parts": [{"title": t, "brief": f"Cover {t.lower()} for this goal."}
                                         for t in PART_SETS[kind]]})
        if self.step == "CONSOLIDATE":
            body = re.sub(r"^.*?(?:between|:|should i (?:buy|get|choose|pick))\s*", "", self.goal, flags=re.I)
            names = re.split(r"\s+(?:or|vs\.?|versus|and)\s+|,\s*", body)
            names = [re.sub(r"^(?:a|an|the)\s+", "", n.strip(" ?."), flags=re.I) for n in names]
            names = [n[:1].upper() + n[1:] for n in names if 1 < len(n) < 40][:4]
            if len(names) < 2:
                names = [f"{_keyword(self.goal)} option A", f"{_keyword(self.goal)} option B"]
            return json.dumps({"options": names, "criteria": ["Price", "Quality", "Fit for the client"]})
        if self.step == "VERDICT":
            return self.verdict()
        if "vote is tied" in self.user:
            first = re.findall(r"- (m\d+) by", self.user)[0]
            return json.dumps({"winner": first, "reason": "It drew the fewest unanswered objections."})
        m = re.search(r"Decision: \[(m\d+)\] by ([A-M]): ([^\n]*?) \(reached by (\w+)\)", self.user)
        title, how = (m.group(3), m.group(4)) if m else ("no proposal", "none")
        return (
            f"**Decision**\n\n{title}, reached by {how}.\n\n"
            "**Why**\n\nIt is the narrowest option with a believable payoff, and the council can "
            "deliver a first version itself.\n\n"
            "**Open objections**\n\n- The costs are still a guess.\n- It needs testing with real people.\n\n"
            "**Next steps**\n\n- Check the numbers.\n- Draft the first version."
        )

    def verdict(self) -> str:
        work = self.user.split("STEP: VERDICT", 1)[0]
        sections = re.findall(r"^### p\d+: (.+?) \(by [A-M]\)\n(.*?)(?=^### p\d+:|\Z)", work, re.M | re.S)
        decided = re.search(r"The council's decision: ([^.\n]+)", self.user)
        heading = f"# {_keyword(self.goal)}: the council's result"
        if sections:
            body = "\n\n".join(f"## {t}\n\n{txt.strip()}" for t, txt in sections)
            if "comparison table" in self.user:
                names = [t for t, _ in sections]
                table = "| Option | Price | Quality | Fit |\n|---|---|---|---|\n" + "\n".join(
                    f"| {n} | {'$' * (i + 1)} | {'★' * (3 + i % 2)} | {'Good' if i == 0 else 'Fair'} |"
                    for i, n in enumerate(names))
                pick = decided.group(1).strip() if decided else names[0]
                other = next((n for n in names if n != pick), names[-1])
                body = (f"{table}\n\n**Recommendation:** {pick}, because it balances price and "
                        f"quality best for this client. Choose {other} if your priorities differ."
                        f"\n\n{body}\n\n_Prices are unverified estimates._")
            return f"{heading}\n\n{body}\n"
        return (f"{heading}\n\n**Short answer:** it depends most on your situation, but for most "
                f"people the council recommends starting small and checking one number first.\n\n"
                "**Why:** members agreed the simplest option is the most likely to work; one member "
                "felt the cost was underestimated.\n\n_This is not professional advice._\n")


def reply(system: str, user: str) -> str:
    return Script(system, user).reply()
