"""The Create mission: logos, illustrations and image sets made by the image consultants.

The moderator drafts a shot list; seats pitch to design each image and the others vote (no
self-votes); each designer writes the brief and picks the consultant; a different seat
reviews it, and a challenged image is regenerated once. The client reviews the gallery.
"""

import asyncio
import re
from collections import Counter
from typing import Any

from app.gateway import images
from app.orchestrator.building import BuildTask
from app.orchestrator.debate import Entry
from app.orchestrator.protocol import AgentReply, ReplyError, Stance

MAX_IMAGES = 4
DEFAULT_SHOTS = [("Logo", "logo", "The primary mark, simple enough to work small."),
                 ("Hero image", "image", "A wide banner that sets the mood.")]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "image"


class CreateMixin:
    """Mixed into MissionRun after BuildMixin (reuses its tasks, statuses and _commission)."""

    async def _step_create(self, step) -> None:
        data = await self._moderator_json(
            "STEP: SHOTLIST",
            f"{step.brief} List the images to make (1 to {MAX_IMAGES}). Reply with only JSON: "
            '{"images": [{"title": "...", "kind": "logo" or "image", "brief": "one sentence"}]}',
            self._direction() or "",
        )
        raw = [i for i in (data or {}).get("images") or [] if isinstance(i, dict) and i.get("title")]
        shots = [(str(i["title"]).strip(), "logo" if str(i.get("kind")) == "logo" else "image",
                  str(i.get("brief", "")).strip()) for i in raw[:MAX_IMAGES]] or DEFAULT_SHOTS
        tasks = [BuildTask(f"i{n + 1}", title, "", f"{brief} ({kind})", [f"site/images/{_slug(title)}.svg"])
                 for n, (title, kind, brief) in enumerate(shots)]
        self.image_kinds = {t.id: kind for t, (_, kind, _) in zip(tasks, shots, strict=True)}
        self._moderator_note("shotlist", "Shot list: " + "; ".join(f"{t.id} {t.title}" for t in tasks) + ".")

        result = await self._elect([(t.id, t.title, t.brief) for t in tasks], what="images to design",
                                   moderator_tiebreak=True)
        load: Counter[str] = Counter()
        present = [s.letter for s in self._present()]
        for t in tasks:
            t.owner = result[t.id][0]
            others = [c for c in present if c != t.owner]
            t.reviewer = min(others, key=lambda c: (load[c], present.index(c))) if others else None
            if t.reviewer:
                load[t.reviewer] += 1
        self.build_tasks = tasks
        for t in tasks:
            self._task_status(t, "planned")
        self._moderator_note("roles", "Designers by vote: " + "; ".join(
            f"{t.title} → {t.owner} (review {t.reviewer})" for t in tasks) + ".")

        self.log.emit("phase_changed", phase=self.phase, round="create")
        gate = asyncio.Semaphore(3)

        async def run(task: BuildTask) -> None:
            async with gate:
                await self._design(task)

        jobs = [asyncio.create_task(run(t)) for t in tasks]
        try:
            await asyncio.gather(*jobs)
        except BaseException:
            for j in jobs:
                j.cancel()
            raise

    async def _design(self, t: BuildTask, feedback: str = "") -> None:
        if not self._ensure_people(t):
            self._task_status(t, "blocked")
            return
        self._task_status(t, "building")
        entry = await self._brief_turn(t, feedback)
        if entry is None:
            self._task_status(t, "blocked")
            return
        await self._make_image(t, entry)
        if feedback or not t.reviewer:
            self._task_status(t, "done")
            return
        self._task_status(t, "in_review")
        review = await self._image_review(t, entry)
        if review is not None and review.stance == Stance.CHALLENGE:
            self._task_status(t, "changes")
            again = await self._brief_turn(t, f"Review from {t.reviewer}: {review.content}")
            if again:
                await self._make_image(t, again)
        self._task_status(t, "done")

    async def _brief_turn(self, t: BuildTask, feedback: str) -> Entry | None:
        seat = self.seat_by_letter[t.owner]
        kind = self.image_kinds.get(t.id, "image")

        def validate(reply: AgentReply) -> None:
            if reply.stance != Stance.REPORT:
                raise ReplyError('Use stance "report".')
            prompt = str((reply.proposal or {}).get("prompt", "")).strip()
            if not prompt or len(prompt) > 1000:
                raise ReplyError('"proposal" must hold "prompt": the image prompt (up to 1000 characters).')
            consultant = str((reply.proposal or {}).get("consultant", "")).strip().lower() or None
            reply.proposal = {"prompt": prompt, "consultant": consultant, "image": t.id}
            reply.reply_to = t.entry_id if feedback else None
            reply.votes = None

        entry = await self._ask(
            seat, "create", f"STEP: IMAGE PROMPT {t.id}",
            f'You are designing {t.id} "{t.title}" ({kind}): {t.brief}\n'
            + (f"Revise it: {feedback}\n" if feedback else "")
            + "Write the prompt an image model will get: subject, style, composition, colours, and any "
            "text that must appear. Pick the consultant from: "
            f"{', '.join(images.available_consultants())} (Recraft's vector model is best for logos). "
            'Use stance "report", content = one sentence on your idea, and "proposal": {"prompt": "...", '
            '"consultant": "..."}.',
            validate, context=self._direction() or "", record=False,
        )
        if entry:
            t.entry_id = entry.id
        return entry

    async def _make_image(self, t: BuildTask, entry: Entry) -> None:
        req = {"path": t.files[0], "prompt": entry.proposal["prompt"], "kind": self.image_kinds.get(t.id, "image"),
               "consultant": entry.proposal.get("consultant")}
        path = await self._commission(entry.seat, req, t.id)
        if path:
            t.files = [path]

    async def _image_review(self, t: BuildTask, entry: Entry) -> Entry | None:
        seat = self.seat_by_letter.get(t.reviewer or "")
        if seat is None or seat.letter in self.absent:
            return None

        def validate(reply: AgentReply) -> None:
            if reply.stance not in (Stance.AGREE, Stance.CHALLENGE):
                raise ReplyError('Use "agree" to approve or "challenge" with a specific change to the prompt.')
            if len(reply.content.strip()) < 15:
                raise ReplyError("Be specific.")
            reply.reply_to = entry.id
            reply.proposal = None
            reply.votes = None

        return await self._ask(
            seat, "review", f"STEP: IMAGE REVIEW {t.id}",
            f'Review the brief for {t.id} "{t.title}" by {t.owner}:\nPROMPT: {entry.proposal["prompt"]}\n'
            f"CONSULTANT: {entry.proposal.get('consultant') or 'default'}\nDoes it fit the chosen concept and "
            'the client? Use "agree", or "challenge" with the specific change the prompt needs.',
            validate, context=self._direction() or "", record=False,
        )

    async def _revise_images(self, note: str) -> None:
        listing = "\n".join(f"- {t.id}: {t.title} ({', '.join(t.files)})" for t in self.build_tasks)
        data = await self._moderator_json(
            "STEP: ROUTE CHANGES",
            f'The client asked for changes: "{note}". Which images must change?\n{listing}\n'
            'Reply with only JSON: {"tasks": ["i1", ...]}',
            self._direction(),
        )
        ids = {t.id for t in self.build_tasks}
        chosen = [str(x) for x in (data or {}).get("tasks") or [] if str(x) in ids] or list(ids)
        self._moderator_note("board", "The client's changes go to: " + ", ".join(chosen) + ".")
        for t in self.build_tasks:
            if t.id in chosen:
                await self._design(t, feedback=f"The client asked: {note}")

    def _gallery(self) -> list[dict[str, Any]]:
        return [{"path": i["path"], "kind": i["kind"], "prompt": i["prompt"], "consultant": i["consultant"],
                 "seat": i["seat"], "task": i.get("task")} for i in self.images]
