"""Scripted assembly replies for the practice server and the tests. No model involved.

Given the exact prompt a seat or the moderator would receive, `reply()` returns a plausible
answer in the right format, so every mission step can run without an API key. Replies are
seeded from the goal, the seat and the step, so a run is repeatable but goals differ.
"""

import hashlib
import json
import random
import re

from app.config import GROUP_NAME

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
    f"Agreed. It plays to what this {GROUP_NAME} can actually do end to end.",
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
        step = re.search(r"STEP: ([A-Z ]+?)(?: ([pti]\d+))?\.", user)
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
            "REVISE PART": self.revise_part, "BUILD TASK": self.build_task,
            "REVISE TASK": self.revise_task, "REVIEW TASK": self.review_task, "ANSWER": self.answer,
            "IMAGE PROMPT": self.image_prompt, "IMAGE REVIEW": self.image_review,
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
        ids = re.findall(r"^- ([pw]\d+):", self.user, re.M)
        picks = [i for i in ids if self.rng.random() < 0.45][:2]
        pitch = ("I'm strongest at clear structure and concrete detail." if picks
                 else "I'll sit this one out and review instead.")
        return self._json("propose", None, pitch, proposal={"parts": picks, "pitch": pitch})

    def role_vote(self) -> str:
        votes = []
        for pid, cands in re.findall(r"^- ([pw]\d+) \([^)]*\): ([A-M](?:, [A-M])*)", self.user, re.M):
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
            f"**{name}.** Revised after the {GROUP_NAME}'s notes: for \"{self.goal}\", the key point is "
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

    # ------------------------------------------------------------ building

    def plan(self) -> str:
        ws = re.findall(r"^- (w\d+): ([^(]+?) \(lead", self.user, re.M)
        ids = [w for w, _ in ws] or ["w1"]
        pick = lambda i: ids[min(i, len(ids) - 1)]
        if "launch kit" in self.user or "landing page (static site)" in self.user:
            tasks = [
                {"id": "t1", "title": "Landing page", "workstream": pick(0), "brief": "Hero, features, signup.",
                 "files": ["site/index.html", "site/styles.css", "site/script.js"], "depends_on": []},
                {"id": "t2", "title": "Marketing copy and launch plan", "workstream": pick(1),
                 "brief": "Taglines, posts, 30-day plan.", "files": ["docs/marketing-copy.md", "docs/launch-plan.md"],
                 "depends_on": []},
                {"id": "t3", "title": "Business plan and pitch", "workstream": pick(2), "brief": "Lean plan, deck text.",
                 "files": ["docs/business-plan.md", "docs/pitch-deck.md"], "depends_on": ["t2"]},
            ]
        else:
            tasks = [
                {"id": "t1", "title": "Copy", "workstream": pick(0), "brief": "Headline and sections.",
                 "files": ["docs/copy.md"], "depends_on": []},
                {"id": "t2", "title": "Page structure", "workstream": pick(1), "brief": "The page itself.",
                 "files": ["site/index.html"], "depends_on": ["t1"]},
                {"id": "t3", "title": "Styling", "workstream": pick(2), "brief": "The look.",
                 "files": ["site/styles.css"], "depends_on": ["t2"]},
                {"id": "t4", "title": "Interactivity", "workstream": pick(3), "brief": "Signup and reveals.",
                 "files": ["site/script.js"], "depends_on": ["t2"]},
            ]
        return json.dumps({"tasks": tasks})

    def _files_reply(self, stance: str, content: str, revised: bool, reply_to: str | None = None,
                     extra: dict | None = None) -> str:
        listed = (re.search(r"Write: ([^\n]+?)\.\n", self.user)
                  or re.search(r'Revise task t\d+ "[^"]*" \(([^)]*)\)', self.user))
        paths = [p.strip() for p in (listed.group(1) if listed else "").split(",") if "/" in p]
        title, summary = _idea_from(self.user)
        # The page gets a logo: requested by whoever writes index.html, or already made.
        writes_index = "site/index.html" in paths
        logo_exists = "site/logo." in self.user.split("Images that already exist:")[-1][:400]
        asks_logo = writes_index and not logo_exists
        # A first build of the script sometimes ships a bug, so the Integrate phase has work to do.
        fixing = "failed" in self.user and "Docker" in self.user
        buggy = not fixing and _rng(self.goal, "bug").random() < 0.5  # reviews miss it; the check catches it
        proposal = dict(extra or {})
        if asks_logo:
            proposal["images"] = [{"path": "site/logo.svg", "kind": "logo", "consultant": "recraft",
                                   "prompt": f'A minimal geometric logo mark for "{title}": rounded square, '
                                             "two-tone gradient, bold initials, works at 32px."}]
        head = json.dumps({"stance": stance, "reply_to": reply_to, "content": content,
                           "proposal": proposal or None}, indent=1)
        blocks = "".join(
            f"=== FILE: {p} ===\n{site_file(p, title, summary, revised or fixing, logo=writes_index, buggy=buggy)}"
            "\n=== END FILE ===\n" for p in paths)
        return head + "\n" + blocks

    def build_task(self) -> str:
        can_ask = "You can ask once." in self.user and "ANSWER to your question" not in self.user
        if can_ask and "docs/copy.md" not in self.user.split("FILES YOU CAN SEE")[0] and self.rng.random() < 0.3:
            lead = re.findall(r"owner ([A-M]),", self.user)
            to = next((x for x in lead if x != self.letter), "A")
            return self._json("question", None, "Before I start: which section should lead the page?",
                              proposal={"to": to, "question": "Which section should lead the page, and what tone?"})
        return self._files_reply("report", "Built my part of the site to match the plan.", revised=False)

    def revise_task(self) -> str:
        m = re.search(r'reply_to "(m\d+)"', self.user)
        if "failed" in self.user and "Docker" in self.user:
            # Claims success with no evidence: the fact-checking guardrail marks it unverified.
            content = "Fixed the errors from the check; it works now."
        else:
            content = "Applied the review: tightened the copy and fixed the details."
        return self._files_reply("report", content, revised=True, reply_to=m.group(1) if m else None)

    def image_prompt(self) -> str:
        title, summary = _idea_from(self.user)
        m = re.search(r'designing (i\d+) "([^"]+)" \((logo|image)\)', self.user)
        what, kind = (m.group(2), m.group(3)) if m else ("Image", "image")
        revised = "Revise it:" in self.user
        prompt = (f'{"A bolder, simpler" if revised else "A clean"} {what.lower()} for "{title}": {summary} '
                  f'{"Flat vector mark, two colours, no text." if kind == "logo" else "Soft gradients, generous space, the name set large."}')
        consultant = "recraft" if kind == "logo" else ("flux" if self.rng.random() < 0.5 else "openai")
        return self._json("report", None, f"{'Simplified' if revised else 'Drafted'} the brief for the {what.lower()}.",
                          proposal={"prompt": prompt, "consultant": consultant})

    def image_review(self) -> str:
        if self.rng.random() < 0.5:
            return self._json("challenge", None, "Make it simpler: fewer elements, and keep the brand colours.")
        return self._json("agree", None, "The brief fits the concept and will read well at small sizes.")

    def review_task(self) -> str:
        final = "final review round" in self.user
        if not final and self.rng.random() < 0.5:
            return self._json("challenge", None, 'The hero needs proof: add a short customer quote under '
                              '"Join the waitlist" and make the accent colour warmer.')
        return self._json("agree", None, "Looks good: it matches the plan, links the other files and reads clearly.")

    def answer(self) -> str:
        return self._json("report", None, "Lead with the hero and the waitlist; keep the tone warm and direct.")

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
        if self.step == "WORKSTREAMS":
            if "launch kit" in self.user:
                ws = [("Website", "The landing page."), ("Copy and launch plan", "Copy and a launch plan."),
                      ("Business plan and pitch", "Plan and pitch deck text.")]
            else:
                ws = [("Copy", "The words on the page."), ("Page structure", "The HTML."),
                      ("Styling", "The CSS."), ("Interactivity", "The JavaScript.")]
            return json.dumps({"workstreams": [{"title": a, "brief": b} for a, b in ws]})
        if self.step == "PLAN":
            return self.plan()
        if self.step == "TIEBREAK":
            tied = re.findall(r"^- ([A-M]) \(", self.user, re.M)
            return json.dumps({"winner": tied[0] if tied else "A", "reason": "The most concrete pitch."})
        if self.step == "ROUTE CHANGES":
            site = re.findall(r"^- ([ti]\d+): [^(]*\(([^)]*site/[^)]*)\)", self.user, re.M)
            return json.dumps({"tasks": [tid for tid, _ in site][:2]})
        if self.step == "SHOTLIST":
            return json.dumps({"images": [
                {"title": "Logo", "kind": "logo", "brief": "A bold, simple mark."},
                {"title": "Hero banner", "kind": "image", "brief": "A wide banner in the brand colours."},
                {"title": "Social card", "kind": "image", "brief": "A square image for posts."},
            ]})
        if self.step == "CONSISTENCY":
            if "docs/pitch-deck.md" in self.user:
                return json.dumps({"issues": [{"file": "docs/pitch-deck.md",
                                               "problem": "The pitch deck uses a different product name than the site.",
                                               "fix": "Use the name from the site's title everywhere."}]})
            return json.dumps({"issues": []})
        if "vote is tied" in self.user:
            first = re.findall(r"- (m\d+) by", self.user)[0]
            return json.dumps({"winner": first, "reason": "It drew the fewest unanswered objections."})
        m = re.search(r"Decision: \[(m\d+)\] by ([A-M]): ([^\n]*?) \(reached by (\w+)\)", self.user)
        title, how = (m.group(3), m.group(4)) if m else ("no proposal", "none")
        return (
            f"**Decision**\n\n{title}, reached by {how}.\n\n"
            f"**Why**\n\nIt is the narrowest option with a believable payoff, and the {GROUP_NAME} can "
            "deliver a first version itself.\n\n"
            "**Open objections**\n\n- The costs are still a guess.\n- It needs testing with real people.\n\n"
            "**Next steps**\n\n- Check the numbers.\n- Draft the first version."
        )

    def verdict(self) -> str:
        work = self.user.split("STEP: VERDICT", 1)[0]
        if "WHAT THE COUNCIL BUILT" in work:
            title, summary = _idea_from(self.user)
            built = re.findall(r"^- t\d+ ([^:]+): ([^(]+) \(built by ([A-M]), reviewed by ([A-M])", work, re.M)
            rows = "\n".join(f"| {files.strip()} | {name} | {by} | {rev} |" for name, files, by, rev in built)
            kit = "launch kit" if "docs/business-plan.md" in work else "site"
            return (f"# {title}\n\n{summary}\n\n## What the {GROUP_NAME} built\n\n| Files | Task | Built by | "
                    f"Reviewed by |\n|---|---|---|---|\n{rows}\n\n## How to open it\n\nOpen the Vault and "
                    f"choose **Preview**, or download `site/index.html` with its CSS and JS files and open it "
                    f"in a browser. The {kit} is plain HTML, CSS and JavaScript, with no server needed.\n")
        sections = re.findall(r"^### p\d+: (.+?) \(by [A-M]\)\n(.*?)(?=^### p\d+:|\Z)", work, re.M | re.S)
        decided = re.search(rf"The {re.escape(GROUP_NAME)}'s decision: ([^.\n]+)", self.user)
        heading = f"# {_keyword(self.goal)}: the {GROUP_NAME}'s result"
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
                f"people the {GROUP_NAME} recommends starting small and checking one number first.\n\n"
                "**Why:** members agreed the simplest option is the most likely to work; one member "
                "felt the cost was underestimated.\n\n_This is not professional advice._\n")


def _idea_from(user: str) -> tuple[str, str]:
    m = re.search(r"Chosen direction: ([^:\n]+): ([^\n]*)", user)
    return (m.group(1).strip(), m.group(2).strip()) if m else ("Our project", "A small, friendly website.")


def site_file(path: str, title: str, summary: str, revised: bool = False, logo: bool = False,
              buggy: bool = False) -> str:
    """A small but real static site, so the preview shows something that works."""
    features = [("Made for you", "Built around one clear job, done well."),
                ("Fast to start", "No setup. Open it and go."),
                ("Fair pricing", "Free to try, simple when you grow.")]
    if path.endswith("index.html"):
        extra = ('\n    <section class="quote reveal"><blockquote>"Exactly what I needed, without the fuss."'
                 "</blockquote><p>— an early user</p></section>") if revised else ""
        cards = "\n".join(f'      <article class="card reveal"><h3>{h}</h3><p>{p}</p></article>' for h, p in features)
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="styles.css">
  <script src="script.js" defer></script>
</head>
<body>
  <header class="nav"><span class="brand">{'<img src="logo.svg" alt="" class="logo">' if logo else ""}{title}</span><a href="#join" class="nav-cta">Get early access</a></header>
  <main>
    <section class="hero">
      <h1>{title}</h1>
      <p class="lead">{summary}</p>
      <button id="cta" class="button">Join the waitlist</button>
    </section>
    <section class="grid">
{cards}
    </section>{extra}
    <section id="join" class="join reveal">
      <h2>Be first in line</h2>
      <form id="signup"><input type="email" placeholder="you@example.com" required><button class="button">Notify me</button></form>
    </section>
  </main>
  <footer>© <span id="year"></span> {title}</footer>
  <div id="toast" role="status" aria-live="polite"></div>
</body>
</html>"""
    if path.endswith(".css"):
        accent = "#ff8a5b" if revised else "#7c6cf2"
        return f""":root {{ --bg: #0f1020; --text: #f4f2ee; --muted: #a9a8b8; --accent: {accent}; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: system-ui, sans-serif; background: radial-gradient(circle at 50% 0%, #23244a, var(--bg) 60%); color: var(--text); }}
.nav {{ display: flex; justify-content: space-between; align-items: center; padding: 20px 6vw; }}
.brand {{ font-weight: 700; letter-spacing: .04em; display: flex; align-items: center; gap: 10px; }}
.logo {{ width: 36px; height: 36px; }}
.nav-cta {{ color: var(--text); opacity: .8; text-decoration: none; }}
.hero {{ text-align: center; padding: 12vh 6vw 8vh; }}
.hero h1 {{ font-size: clamp(2.4rem, 6vw, 4.4rem); margin: 0 0 16px; }}
.lead {{ color: var(--muted); font-size: 1.2rem; max-width: 640px; margin: 0 auto 32px; }}
.button {{ background: var(--accent); color: white; border: 0; border-radius: 999px; padding: 14px 28px; font-size: 1rem; cursor: pointer; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; padding: 0 6vw 10vh; }}
.card {{ background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.1); border-radius: 16px; padding: 24px; }}
.card p, footer {{ color: var(--muted); }}
.quote {{ text-align: center; padding: 0 6vw 8vh; font-size: 1.3rem; }}
.join {{ text-align: center; padding: 6vh 6vw 10vh; }}
.join form {{ display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; }}
.join input {{ padding: 14px 18px; border-radius: 999px; border: 1px solid rgba(255,255,255,.2); background: transparent; color: var(--text); min-width: 260px; }}
footer {{ text-align: center; padding: 30px; }}
.reveal {{ opacity: 0; transform: translateY(16px); transition: all .6s ease; }}
.reveal.shown {{ opacity: 1; transform: none; }}
#toast {{ position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); background: #1e1f3a; padding: 12px 20px; border-radius: 12px; opacity: 0; transition: opacity .3s; }}
#toast.on {{ opacity: 1; }}"""
    if path.endswith(".js"):
        return """const toast = document.getElementById("toast");
function say(text) {
  toast.textContent = text;
  toast.classList.add("on");
  setTimeout(() => toast.classList.remove("on"), 2200);
}
document.getElementById("year").textContent = new Date().getFullYear();
document.getElementById("cta").addEventListener("click", () => {
  document.getElementById("join").scrollIntoView({ behavior: "smooth" });
});
document.getElementById("signup").addEventListener("submit", (event) => {
  event.preventDefault();
  say("Thanks! You're on the list.");
  event.target.reset();
});
const observer = new IntersectionObserver((entries) => {
  entries.forEach((e) => { if (e.isIntersecting) e.target.classList.add("shown"); });
}, { threshold: 0.15 });
document.querySelectorAll(".reveal").forEach((el) => observer.observe(el));""" + (
            "\ninitCarousel(); // the carousel helper was never written" if buggy else "")
    name = path.rsplit("/", 1)[-1].replace("-", " ").replace(".md", "").capitalize()
    body = (f"# {name}: {title}\n\n{summary}\n\n## Key points\n\n"
            "- Who it is for and the one job it does.\n- Why now, and why us.\n"
            "- The first milestone and how we will know it worked.\n")
    return body + ("\n## Revised\n\nTightened after review.\n" if revised else "")


def reply(system: str, user: str) -> str:
    return Script(system, user).reply()
