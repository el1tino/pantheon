"""Recorded demo runs, replayed with no API calls.

A demo is a folder under demo/ holding a finished run: run.json (the run row), events.json.gz
(the whole event log with timestamps) and files/ (everything the run wrote). On start-up each
demo is imported as a public, read-only run, so Replay, the Vault and the site preview work for
it exactly as for a live run, with nothing sent to any model.
"""

import gzip
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.db import Event, Run
from app.orchestrator import sandbox


def _demo_dirs() -> list[Path]:
    root = get_settings().demo_dir
    return sorted(p for p in root.iterdir() if (p / "run.json").is_file()) if root.is_dir() else []


def _unchanged(session: Session, run: Run, meta: dict, events: list[dict]) -> bool:
    """Already imported from this same recording: same run details and the very same events."""
    if run.phase != meta.get("phase") or run.spent_usd != meta.get("spent_usd"):
        return False
    rows = session.exec(select(Event).where(Event.run_id == run.id).order_by(Event.seq)).all()
    return len(rows) == len(events) and all(
        r.type == e["type"] and json.loads(r.payload_json) == e["payload"] for r, e in zip(rows, events, strict=True)
    )


def import_demos(session: Session) -> list[str]:
    imported = []
    for folder in _demo_dirs():
        meta = json.loads((folder / "run.json").read_text())
        run_id = meta["id"]
        existing = session.get(Run, run_id)
        if existing and not existing.public:
            continue  # never overwrite a real run that happens to share the id
        with gzip.open(folder / "events.json.gz", "rt", encoding="utf-8") as f:
            events = json.load(f)
        if existing and _unchanged(session, existing, meta, events):
            continue
        if existing:
            for ev in session.exec(select(Event).where(Event.run_id == run_id)).all():
                session.delete(ev)
            session.delete(existing)
            session.commit()
        session.add(Run(id=run_id, goal=meta["goal"], status=meta.get("status", "done"),
                        phase=meta.get("phase", "done"), budget_usd=meta.get("budget_usd", 0),
                        spent_usd=meta.get("spent_usd", 0), public=True, owner_id=None))
        for ev in events:
            session.add(Event(run_id=run_id, seq=ev["seq"], type=ev["type"],
                              payload_json=json.dumps(ev["payload"]),
                              at=datetime.fromtimestamp(ev["at"], tz=timezone.utc)))
        session.commit()
        sandbox.run_dir(run_id)  # creates the run folder
        files = folder / "files"
        if files.is_dir():
            for src in files.rglob("*"):
                if src.is_file():
                    rel = src.relative_to(files).as_posix()
                    dest = sandbox.safe_path(run_id, rel)  # refuses anything outside the run folder
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dest)
        imported.append(run_id)
    return imported


def export_demo(session: Session, run_id: str, slug: str) -> Path:
    """Save a finished run as a demo folder (python -m app.cli export-demo RUN_ID SLUG)."""
    run = session.get(Run, run_id)
    if not run:
        raise ValueError(f"No run {run_id}")
    folder = get_settings().demo_dir / slug
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "files").mkdir(parents=True)
    demo_id = f"demo-{slug}"
    (folder / "run.json").write_text(json.dumps({
        "id": demo_id, "goal": run.goal, "status": run.status, "phase": run.phase,
        "budget_usd": run.budget_usd, "spent_usd": run.spent_usd,
    }, indent=2) + "\n")
    rows = session.exec(select(Event).where(Event.run_id == run_id).order_by(Event.seq)).all()
    events = []
    for r in rows:
        at = r.at if r.at.tzinfo else r.at.replace(tzinfo=timezone.utc)
        events.append({"seq": r.seq, "type": r.type, "payload": json.loads(r.payload_json), "at": at.timestamp()})
    with gzip.open(folder / "events.json.gz", "wt", encoding="utf-8") as f:
        json.dump(events, f, separators=(",", ":"))
    src = sandbox.run_dir(run_id)
    for path in src.rglob("*"):
        if path.is_file():
            dest = folder / "files" / path.relative_to(src)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
    return folder
